#!/usr/bin/env python3
"""Benchmark direct object-storage and gateway HTTP download paths."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import secrets
import statistics
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote, urljoin

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError
import httpx


MIB = 1024 * 1024
DEFAULT_PATHS = (
    "direct",
    "gateway-presigned",
    "gateway-presigned-e2e",
    "gateway-share",
)


@dataclass(frozen=True)
class Sample:
    status_code: int | None
    bytes_received: int
    ttfb_ms: float | None
    total_ms: float
    control_plane_ms: float | None = None
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare direct S3, s3BEAR presigned, s3BEAR share-proxy, and "
            "optional external gateway download paths. Credentials are read from "
            "environment variables; they are never written to the report."
        )
    )
    parser.add_argument("--gateway-url", default="http://localhost:8200")
    parser.add_argument("--s3-endpoint", default="http://localhost:9000")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--bucket", default="s3bear-benchmark")
    parser.add_argument("--key", help="Object key; defaults to bench/<size>.bin")
    parser.add_argument("--size-mib", type=int, default=16)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument(
        "--paths",
        default=",".join(DEFAULT_PATHS),
        help=(
            "Comma-separated built-in paths: direct,gateway-presigned,"
            "gateway-presigned-e2e,gateway-share"
        ),
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="NAME=URL",
        help="Additional HTTP gateway target. May be repeated.",
    )
    parser.add_argument("--force-upload", action="store_true")
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--seed",
        type=int,
        help="Target-order seed; generated and recorded when omitted.",
    )
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()

    if args.size_mib < 1:
        parser.error("--size-mib must be at least 1")
    if args.requests < 1:
        parser.error("--requests must be at least 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.warmup < 0:
        parser.error("--warmup cannot be negative")

    requested_paths = tuple(filter(None, (path.strip() for path in args.paths.split(","))))
    unknown_paths = sorted(set(requested_paths) - set(DEFAULT_PATHS))
    if unknown_paths:
        parser.error(f"unknown built-in path(s): {', '.join(unknown_paths)}")
    args.paths = requested_paths
    return args


def build_s3_client(args: argparse.Namespace):
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise RuntimeError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required")
    return boto3.client(
        "s3",
        endpoint_url=args.s3_endpoint,
        region_name=args.region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_test_object(client: Any, bucket: str, key: str, size_bytes: int, force: bool) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        client.create_bucket(Bucket=bucket)

    if not force:
        try:
            response = client.head_object(Bucket=bucket, Key=key)
            if response.get("ContentLength") == size_bytes:
                return
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code not in {"404", "NoSuchKey", "NotFound"}:
                raise

    print(f"Preparing s3://{bucket}/{key} ({size_bytes / MIB:.0f} MiB)...")
    with tempfile.TemporaryFile() as source:
        source.truncate(size_bytes)
        source.seek(0)
        client.upload_fileobj(
            source,
            bucket,
            key,
            ExtraArgs={"ContentType": "application/octet-stream"},
            Config=TransferConfig(
                multipart_threshold=8 * MIB,
                multipart_chunksize=8 * MIB,
                max_concurrency=4,
            ),
        )


def parse_external_targets(values: list[str]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for value in values:
        name, separator, url = value.partition("=")
        if not separator or not name.strip() or not url.strip():
            raise ValueError(f"invalid --target {value!r}; expected NAME=URL")
        if name.strip() in targets or name.strip() in DEFAULT_PATHS:
            raise ValueError(f"duplicate target name: {name.strip()}")
        targets[name.strip()] = url.strip()
    return targets


def shuffled_target_names(targets: dict[str, Any], seed: int) -> list[str]:
    names = list(targets)
    random.Random(seed).shuffle(names)
    return names


async def gateway_token(client: httpx.AsyncClient, gateway_url: str) -> tuple[str, float]:
    existing_token = os.getenv("S3BEAR_BENCH_TOKEN")
    if existing_token:
        return existing_token, 0.0

    username = os.getenv("S3BEAR_BENCH_USERNAME")
    password = os.getenv("S3BEAR_BENCH_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "gateway paths require S3BEAR_BENCH_TOKEN or both "
            "S3BEAR_BENCH_USERNAME and S3BEAR_BENCH_PASSWORD"
        )

    started = time.perf_counter()
    response = await client.post(
        urljoin(gateway_url.rstrip("/") + "/", "api/v1/auth/token"),
        data={"username": username, "password": password},
    )
    response.raise_for_status()
    return response.json()["access_token"], (time.perf_counter() - started) * 1000


async def gateway_targets(
    client: httpx.AsyncClient,
    gateway_url: str,
    bucket: str,
    key: str,
    token: str,
    paths: tuple[str, ...],
) -> tuple[dict[str, str], dict[str, float]]:
    headers = {"Authorization": f"Bearer {token}"}
    targets: dict[str, str] = {}
    timings: dict[str, float] = {}
    encoded_bucket = quote(bucket, safe="")

    if "gateway-presigned" in paths:
        started = time.perf_counter()
        response = await client.post(
            urljoin(
                gateway_url.rstrip("/") + "/",
                f"api/v1/buckets/{encoded_bucket}/presign",
            ),
            headers=headers,
            json={"key": key},
        )
        response.raise_for_status()
        targets["gateway-presigned"] = response.json()["url"]
        timings["gateway_presign_ms"] = (time.perf_counter() - started) * 1000

    if "gateway-share" in paths:
        encoded_key = quote(key, safe="/")
        started = time.perf_counter()
        response = await client.post(
            urljoin(
                gateway_url.rstrip("/") + "/",
                f"api/v1/share/{encoded_bucket}/{encoded_key}",
            ),
            headers=headers,
            json={"expires_in": "1h"},
        )
        response.raise_for_status()
        share_path = response.json()["url"]
        targets["gateway-share"] = urljoin(gateway_url.rstrip("/") + "/", share_path.lstrip("/"))
        timings["share_create_ms"] = (time.perf_counter() - started) * 1000

    return targets, timings


async def fetch_once(
    client: httpx.AsyncClient,
    url: str,
    expected_bytes: int,
    *,
    started: float | None = None,
    control_plane_ms: float | None = None,
) -> Sample:
    started = started or time.perf_counter()
    first_byte_at: float | None = None
    received = 0
    status_code: int | None = None
    try:
        async with client.stream("GET", url) as response:
            status_code = response.status_code
            async for chunk in response.aiter_raw():
                if chunk and first_byte_at is None:
                    first_byte_at = time.perf_counter()
                received += len(chunk)
        finished = time.perf_counter()
        error = None
        if not 200 <= status_code < 300:
            error = f"HTTP {status_code}"
        elif received != expected_bytes:
            error = f"expected {expected_bytes} bytes, received {received}"
        return Sample(
            status_code=status_code,
            bytes_received=received,
            ttfb_ms=(first_byte_at - started) * 1000 if first_byte_at else None,
            total_ms=(finished - started) * 1000,
            control_plane_ms=control_plane_ms,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001 - benchmark errors belong in the report
        return Sample(
            status_code=status_code,
            bytes_received=received,
            ttfb_ms=(first_byte_at - started) * 1000 if first_byte_at else None,
            total_ms=(time.perf_counter() - started) * 1000,
            control_plane_ms=control_plane_ms,
            error=f"{type(exc).__name__}: {exc}",
        )


async def fetch_gateway_presigned_once(
    client: httpx.AsyncClient,
    gateway_url: str,
    bucket: str,
    key: str,
    token: str,
    expected_bytes: int,
) -> Sample:
    started = time.perf_counter()
    encoded_bucket = quote(bucket, safe="")
    try:
        response = await client.post(
            urljoin(
                gateway_url.rstrip("/") + "/",
                f"api/v1/buckets/{encoded_bucket}/presign",
            ),
            headers={"Authorization": f"Bearer {token}"},
            json={"key": key},
        )
        control_plane_ms = (time.perf_counter() - started) * 1000
        if not 200 <= response.status_code < 300:
            return Sample(
                status_code=response.status_code,
                bytes_received=0,
                ttfb_ms=None,
                total_ms=control_plane_ms,
                control_plane_ms=control_plane_ms,
                error=f"presign HTTP {response.status_code}",
            )
        return await fetch_once(
            client,
            response.json()["url"],
            expected_bytes,
            started=started,
            control_plane_ms=control_plane_ms,
        )
    except Exception as exc:  # noqa: BLE001 - benchmark errors belong in the report
        elapsed_ms = (time.perf_counter() - started) * 1000
        return Sample(
            status_code=None,
            bytes_received=0,
            ttfb_ms=None,
            total_ms=elapsed_ms,
            control_plane_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_target(
    sample_factory,
    requests: int,
    concurrency: int,
    warmup: int,
    timeout_seconds: float,
) -> tuple[list[Sample], float]:
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
    ) as client:
        for _ in range(warmup):
            await sample_factory(client)

        queue: asyncio.Queue[int] = asyncio.Queue()
        for request_number in range(requests):
            queue.put_nowait(request_number)

        samples: list[Sample] = []

        async def worker() -> None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                samples.append(await sample_factory(client))
                queue.task_done()

        started = time.perf_counter()
        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, requests))]
        await asyncio.gather(*workers)
        elapsed = time.perf_counter() - started
    return samples, elapsed


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "min": min(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def summarize(samples: list[Sample], elapsed: float) -> dict[str, Any]:
    successful = [sample for sample in samples if sample.error is None]
    total_bytes = sum(sample.bytes_received for sample in successful)
    ttfb_values = [sample.ttfb_ms for sample in successful if sample.ttfb_ms is not None]
    latency_values = [sample.total_ms for sample in successful]
    control_plane_values = [
        sample.control_plane_ms
        for sample in successful
        if sample.control_plane_ms is not None
    ]
    errors: dict[str, int] = {}
    for sample in samples:
        if sample.error:
            errors[sample.error] = errors.get(sample.error, 0) + 1
    return {
        "requests": len(samples),
        "successful_requests": len(successful),
        "failed_requests": len(samples) - len(successful),
        "elapsed_seconds": elapsed,
        "requests_per_second": len(successful) / elapsed if elapsed else 0.0,
        "throughput_mib_per_second": total_bytes / MIB / elapsed if elapsed else 0.0,
        "control_plane_ms": distribution(control_plane_values),
        "ttfb_ms": distribution(ttfb_values),
        "latency_ms": distribution(latency_values),
        "errors": errors,
        "samples": [asdict(sample) for sample in samples],
    }


def add_baseline_comparison(results: dict[str, dict[str, Any]]) -> None:
    baseline = results.get("direct")
    if not baseline:
        return
    baseline_throughput = baseline["throughput_mib_per_second"]
    baseline_p95 = baseline["latency_ms"]["p95"]
    for result in results.values():
        throughput = result["throughput_mib_per_second"]
        p95 = result["latency_ms"]["p95"]
        result["vs_direct"] = {
            "throughput_change_percent": (
                (throughput / baseline_throughput - 1) * 100 if baseline_throughput else None
            ),
            "p95_latency_change_percent": (
                (p95 / baseline_p95 - 1) * 100
                if p95 is not None and baseline_p95
                else None
            ),
        }


def format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def print_summary(results: dict[str, dict[str, Any]]) -> None:
    header = (
        f"{'target':<22} {'ok':>6} {'err':>5} {'req/s':>9} {'MiB/s':>10} "
        f"{'TTFB p95':>10} {'total p95':>11} {'vs direct':>11}"
    )
    print(f"\n{header}")
    print("-" * len(header))
    for name, result in results.items():
        comparison = result.get("vs_direct", {}).get("throughput_change_percent")
        comparison_text = "-" if comparison is None else f"{comparison:+.1f}%"
        print(
            f"{name:<22} {result['successful_requests']:>6} {result['failed_requests']:>5} "
            f"{result['requests_per_second']:>9.2f} "
            f"{result['throughput_mib_per_second']:>10.2f} "
            f"{format_number(result['ttfb_ms']['p95']):>10} "
            f"{format_number(result['latency_ms']['p95']):>11} "
            f"{comparison_text:>11}"
        )


async def async_main(args: argparse.Namespace) -> int:
    size_bytes = args.size_mib * MIB
    key = args.key or f"bench/{args.size_mib}mib.bin"
    external_targets = parse_external_targets(args.target)
    needs_s3 = "direct" in args.paths or not args.skip_prepare
    s3_client = build_s3_client(args) if needs_s3 else None

    if not args.skip_prepare:
        assert s3_client is not None
        ensure_test_object(s3_client, args.bucket, key, size_bytes, args.force_upload)

    targets: dict[str, Any] = {}
    control_plane: dict[str, float] = {}
    if "direct" in args.paths:
        assert s3_client is not None
        direct_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": args.bucket, "Key": key},
            ExpiresIn=3600,
        )

        async def fetch_direct(client: httpx.AsyncClient) -> Sample:
            return await fetch_once(client, direct_url, size_bytes)

        targets["direct"] = fetch_direct

    gateway_paths = tuple(path for path in args.paths if path.startswith("gateway-"))
    if gateway_paths:
        async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
            token, login_ms = await gateway_token(client, args.gateway_url)
            generated_targets, timings = await gateway_targets(
                client,
                args.gateway_url,
                args.bucket,
                key,
                token,
                gateway_paths,
            )
        targets.update(generated_targets)
        control_plane["login_ms"] = login_ms
        control_plane.update(timings)

        if "gateway-presigned-e2e" in gateway_paths:
            async def fetch_gateway_e2e(client: httpx.AsyncClient) -> Sample:
                return await fetch_gateway_presigned_once(
                    client,
                    args.gateway_url,
                    args.bucket,
                    key,
                    token,
                    size_bytes,
                )

            targets["gateway-presigned-e2e"] = fetch_gateway_e2e

    targets.update(external_targets)
    if not targets:
        raise RuntimeError("no benchmark targets selected")

    seed = args.seed if args.seed is not None else secrets.randbits(32)
    execution_order = shuffled_target_names(targets, seed)
    print(f"Execution seed: {seed}; order: {', '.join(execution_order)}")
    results: dict[str, dict[str, Any]] = {}
    for name in execution_order:
        target = targets[name]
        print(
            f"Running {name}: {args.requests} requests, "
            f"concurrency {args.concurrency}, warmup {args.warmup}..."
        )
        if isinstance(target, str):
            async def fetch_static(
                client: httpx.AsyncClient,
                target_url: str = target,
            ) -> Sample:
                return await fetch_once(client, target_url, size_bytes)

            sample_factory = fetch_static
        else:
            sample_factory = target
        samples, elapsed = await run_target(
            sample_factory,
            args.requests,
            args.concurrency,
            args.warmup,
            args.timeout_seconds,
        )
        results[name] = summarize(samples, elapsed)

    add_baseline_comparison(results)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "gateway_url": args.gateway_url,
            "s3_endpoint": args.s3_endpoint,
            "bucket": args.bucket,
            "key": key,
            "object_size_bytes": size_bytes,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "warmup": args.warmup,
            "seed": seed,
            "execution_order": execution_order,
        },
        "control_plane_ms": control_plane,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_summary(results)
    print(f"\nReport: {args.output}")
    return 0 if all(result["failed_requests"] == 0 for result in results.values()) else 2


def main() -> int:
    try:
        return asyncio.run(async_main(parse_args()))
    except (ClientError, httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())