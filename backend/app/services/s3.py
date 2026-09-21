import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import AsyncGenerator, Optional
import asyncio
import time

from app.core.config import settings

DEFAULT_CONTENT_TYPE = "application/octet-stream"

# ── Storage-stats cache ───────────────────────────────────────────────────────
# Computing bucket/global size means paginating every object across every
# provider. Quota enforcement runs that on every upload, so the results are
# cached for a short TTL and invalidated whenever an object is written or
# removed. A brief staleness window is acceptable for a quota guard; writes
# invalidate eagerly so the next check sees fresh totals.
_STATS_CACHE_TTL_SECONDS = 30
_bucket_size_cache: dict[str, tuple[float, dict]] = {}   # bucket -> (expires_at, stats)
_storage_stats_cache: Optional[tuple[float, dict]] = None  # (expires_at, stats)


def invalidate_stats_cache(bucket: str | None = None) -> None:
    """Drop cached size stats. Clears the aggregate always; clears one bucket's
    entry when named, or all bucket entries when not."""
    global _storage_stats_cache
    _storage_stats_cache = None
    if bucket is None:
        _bucket_size_cache.clear()
    else:
        _bucket_size_cache.pop(bucket, None)

# ── Multi-provider runtime registry ───────────────────────────────────────────
# s3BEAR can front several S3-compatible backends at once. Each provider holds a
# full connection config; each managed bucket is bound to one provider, and every
# operation on that bucket is routed to it. When no provider is configured yet,
# the environment (AWS_*) config acts as an implicit "env" provider so existing
# single-backend deployments keep working.
#
# Normalized provider cfg shape:
#   {id, name, access_key, secret_key, region, endpoint, presigned_base, use_ssl}
_providers: dict[str, dict] = {}
_default_provider_id: str | None = None
_bucket_map: dict[str, str] = {}  # bucket_name -> provider_id

# boto3 clients are safe to reuse across calls; building one per operation
# re-parses config and reopens connection pools needlessly. Cached by the
# connection parameters that identify a distinct client and cleared whenever
# providers are reloaded.
_client_cache: dict[tuple, object] = {}

ENV_PROVIDER_ID = "env"


def set_providers(providers: list[dict], default_id: str | None = None) -> None:
    """Install the full set of storage providers (replaces the current set)."""
    global _providers, _default_provider_id
    _providers = {p["id"]: p for p in providers}
    if default_id and default_id in _providers:
        _default_provider_id = default_id
    elif providers:
        _default_provider_id = providers[0]["id"]
    else:
        _default_provider_id = None
    # Provider configs changed; drop any boto3 clients built from the old ones.
    _client_cache.clear()


def set_bucket_map(mapping: dict[str, str]) -> None:
    """Install the bucket_name -> provider_id routing map (replaces current)."""
    global _bucket_map
    _bucket_map = dict(mapping)


def register_bucket(bucket_name: str, provider_id: str) -> None:
    _bucket_map[bucket_name] = provider_id


def unregister_bucket(bucket_name: str) -> None:
    _bucket_map.pop(bucket_name, None)


def has_providers() -> bool:
    return bool(_providers)


def _env_cfg() -> dict:
    """The implicit provider derived from environment variables."""
    return {
        "id": ENV_PROVIDER_ID,
        "name": "Environment",
        "access_key": settings.AWS_ACCESS_KEY_ID,
        "secret_key": settings.AWS_SECRET_ACCESS_KEY,
        "region": settings.AWS_REGION,
        "endpoint": settings.AWS_ENDPOINT_URL,
        "presigned_base": settings.PRESIGNED_URL_BASE,
        "use_ssl": True,
    }


def _effective_providers() -> list[dict]:
    """All providers to operate over. Falls back to the env provider when none
    are configured in the database."""
    if _providers:
        return list(_providers.values())
    return [_env_cfg()]


def _resolve_cfg(bucket: str | None = None, provider_id: str | None = None) -> dict:
    """Resolve the effective connection config for an operation.

    Priority: explicit provider_id > the bucket's mapped provider > default
    provider > environment fallback.
    """
    if provider_id and provider_id in _providers:
        return _providers[provider_id]
    if bucket is not None:
        pid = _bucket_map.get(bucket)
        if pid and pid in _providers:
            return _providers[pid]
    if _default_provider_id and _default_provider_id in _providers:
        return _providers[_default_provider_id]
    if _providers:
        return next(iter(_providers.values()))
    return _env_cfg()


def _make_client(bucket: str | None = None, provider_id: str | None = None, cfg: dict | None = None):
    c = cfg or _resolve_cfg(bucket, provider_id)
    endpoint = c.get("endpoint") or ""
    key = ("plain", c["access_key"], c["region"], endpoint)
    client = _client_cache.get(key)
    if client is None:
        kwargs = {
            "aws_access_key_id": c["access_key"],
            "aws_secret_access_key": c["secret_key"],
            "region_name": c["region"],
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        client = boto3.client("s3", **kwargs)
        _client_cache[key] = client
    return client


def _make_presign_client(bucket: str | None = None, provider_id: str | None = None):
    """Client that uses the external-facing URL and SigV4 for presigned URL generation.
    SigV4 is required — MinIO rejects SigV2 presigned URLs for multipart uploads."""
    c = _resolve_cfg(bucket, provider_id)
    endpoint = c.get("presigned_base") or c.get("endpoint") or ""
    key = ("presign", c["access_key"], c["region"], endpoint)
    client = _client_cache.get(key)
    if client is None:
        kwargs = {
            "aws_access_key_id": c["access_key"],
            "aws_secret_access_key": c["secret_key"],
            "region_name": c["region"],
            "config": Config(signature_version="s3v4"),
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        client = boto3.client("s3", **kwargs)
        _client_cache[key] = client
    return client


def normalize_cfg(raw: dict) -> dict:
    """Normalize an arbitrary cfg dict (e.g. from the providers API) to the
    internal shape so it can be passed to _make_client / test_config."""
    return {
        "id": raw.get("id", ""),
        "name": raw.get("name", ""),
        "access_key": raw.get("access_key") or raw.get("access_key_id", ""),
        "secret_key": raw.get("secret_key") or raw.get("secret_access_key", ""),
        "region": raw.get("region") or "us-east-1",
        "endpoint": raw.get("endpoint") or raw.get("endpoint_url", ""),
        "presigned_base": raw.get("presigned_base", ""),
        "use_ssl": raw.get("use_ssl", True),
    }


async def test_config(cfg: dict) -> None:
    """Validate an S3 config by attempting a list_buckets. Raises on failure."""
    client = _make_client(cfg=normalize_cfg(cfg))
    await _run_sync(client.list_buckets)


def _run_sync(func, *args, **kwargs):
    """Run a blocking (boto3) call off the event loop in a worker thread."""
    return asyncio.to_thread(func, *args, **kwargs)


async def create_bucket(bucket_name: str, provider_id: str | None = None) -> None:
    client = _make_client(provider_id=provider_id)
    try:
        await _run_sync(client.create_bucket, Bucket=bucket_name)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
            raise ValueError(f"Bucket '{bucket_name}' already exists")
        raise


async def delete_bucket(bucket_name: str) -> None:
    client = _make_client(bucket=bucket_name)
    try:
        await _run_sync(client.delete_bucket, Bucket=bucket_name)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchBucket":
            raise FileNotFoundError(f"Bucket '{bucket_name}' not found")
        if code == "BucketNotEmpty":
            raise ValueError(f"Bucket '{bucket_name}' is not empty")
        raise


async def list_buckets() -> list[dict]:
    """List buckets across every configured provider, tagging each with the
    provider it lives on. Also refreshes the routing map for discovered buckets
    so externally-created buckets remain addressable."""
    result: list[dict] = []
    seen: set[str] = set()
    for cfg in _effective_providers():
        client = _make_client(cfg=cfg)
        try:
            response = await _run_sync(client.list_buckets)
        except ClientError:
            continue  # a misconfigured provider must not break the whole listing
        for b in response.get("Buckets", []):
            name = b["Name"]
            if name in seen:
                continue
            seen.add(name)
            # Explicit mapping wins; otherwise attribute to the provider we found it on.
            pid = _bucket_map.get(name, cfg["id"])
            if name not in _bucket_map and cfg["id"] != ENV_PROVIDER_ID:
                _bucket_map[name] = cfg["id"]
            result.append({
                "name": name,
                "creation_date": b.get("CreationDate"),
                "provider_id": pid,
                "provider_name": _providers.get(pid, {}).get("name", cfg["name"]),
            })
    return result


async def list_objects(bucket: str, prefix: str = "", delimiter: str = "/") -> dict:
    client = _make_client(bucket=bucket)
    kwargs = {"Bucket": bucket, "Delimiter": delimiter}
    if prefix:
        kwargs["Prefix"] = prefix

    objects = []
    common_prefixes = []
    continuation_token = None

    while True:
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = await _run_sync(client.list_objects_v2, **kwargs)

        for obj in response.get("Contents", []):
            if obj["Key"] == prefix:  # skip the "folder" itself
                continue
            objects.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"],
                "etag": obj.get("ETag", "").strip('"'),
            })

        for cp in response.get("CommonPrefixes", []):
            common_prefixes.append(cp["Prefix"])

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    return {"objects": objects, "common_prefixes": common_prefixes}


async def put_object(bucket: str, key: str, data: bytes, content_type: str = DEFAULT_CONTENT_TYPE) -> None:
    client = _make_client(bucket=bucket)
    await _run_sync(
        client.put_object,
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    invalidate_stats_cache(bucket)


async def upload_fileobj(bucket: str, key: str, fileobj, content_type: str = DEFAULT_CONTENT_TYPE) -> None:
    """Stream a file-like object to S3 without loading it fully into memory.

    boto3's managed transfer reads the object in chunks and switches to a
    multipart upload for large files. The caller keeps ownership of ``fileobj``.
    """
    client = _make_client(bucket=bucket)
    await _run_sync(
        client.upload_fileobj,
        fileobj,
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    invalidate_stats_cache(bucket)


async def delete_objects(bucket: str, keys: list[str]) -> dict:
    client = _make_client(bucket=bucket)
    delete_payload = {"Objects": [{"Key": k} for k in keys], "Quiet": False}
    response = await _run_sync(client.delete_objects, Bucket=bucket, Delete=delete_payload)
    deleted = [d["Key"] for d in response.get("Deleted", [])]
    errors = [e.get("Key", "") for e in response.get("Errors", [])]
    invalidate_stats_cache(bucket)
    return {"deleted": deleted, "errors": errors}


async def stream_object(bucket: str, key: str) -> tuple[AsyncGenerator[bytes, None], str, int]:
    """Returns (async_generator, content_type, content_length)."""
    client = _make_client(bucket=bucket)

    try:
        response = await _run_sync(client.get_object, Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise FileNotFoundError(f"Object not found: {key}")
        raise

    content_type = response.get("ContentType", DEFAULT_CONTENT_TYPE)
    content_length = response.get("ContentLength", 0)
    body = response["Body"]

    async def _generator():
        chunk_size = 64 * 1024
        while True:
            chunk = await asyncio.to_thread(body.read, chunk_size)
            if not chunk:
                break
            yield chunk

    return _generator(), content_type, content_length


class ObjectTooLarge(Exception):
    """Raised when an object exceeds a caller-supplied size limit."""

    def __init__(self, size: int):
        self.size = size
        super().__init__(f"Object is {size} bytes")


async def get_object_bytes(bucket: str, key: str, max_bytes: int | None = None) -> tuple[bytes, str]:
    """Read a full object into memory. Returns (data, content_type).
    Raises FileNotFoundError if missing, ObjectTooLarge if it exceeds max_bytes."""
    client = _make_client(bucket=bucket)
    try:
        response = await _run_sync(client.get_object, Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise FileNotFoundError(f"Object not found: {key}")
        raise

    content_type = response.get("ContentType", DEFAULT_CONTENT_TYPE)
    content_length = response.get("ContentLength", 0)
    body = response["Body"]
    if max_bytes is not None and content_length and content_length > max_bytes:
        body.close()
        raise ObjectTooLarge(content_length)

    data = await _run_sync(body.read)
    return data, content_type


async def get_bucket_size(bucket_name: str) -> dict:
    """Return total size and object count for a bucket (short-TTL cached)."""
    cached = _bucket_size_cache.get(bucket_name)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    client = _make_client(bucket=bucket_name)
    total_size = 0
    object_count = 0
    continuation_token = None

    while True:
        kwargs = {"Bucket": bucket_name}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = await _run_sync(client.list_objects_v2, **kwargs)

        for obj in response.get("Contents", []):
            total_size += obj["Size"]
            object_count += 1

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    stats = {"size": total_size, "object_count": object_count}
    _bucket_size_cache[bucket_name] = (time.monotonic() + _STATS_CACHE_TTL_SECONDS, stats)
    return stats


async def get_storage_stats() -> dict:
    """Return aggregate storage stats across all buckets (short-TTL cached)."""
    global _storage_stats_cache
    if _storage_stats_cache and _storage_stats_cache[0] > time.monotonic():
        return _storage_stats_cache[1]

    buckets = await list_buckets()
    bucket_stats = []
    total_size = 0
    total_objects = 0

    for b in buckets:
        stats = await get_bucket_size(b["name"])
        bucket_stats.append({
            "name": b["name"],
            "size": stats["size"],
            "object_count": stats["object_count"],
            "provider_id": b.get("provider_id"),
            "provider_name": b.get("provider_name"),
        })
        total_size += stats["size"]
        total_objects += stats["object_count"]

    result = {
        "total_size": total_size,
        "total_objects": total_objects,
        "bucket_count": len(buckets),
        "buckets": bucket_stats,
    }
    _storage_stats_cache = (time.monotonic() + _STATS_CACHE_TTL_SECONDS, result)
    return result


async def create_multipart_upload(bucket: str, key: str, content_type: str = DEFAULT_CONTENT_TYPE) -> str:
    """Initiate a multipart upload. Returns the upload ID."""
    client = _make_client(bucket=bucket)
    response = await _run_sync(
        client.create_multipart_upload,
        Bucket=bucket,
        Key=key,
        ContentType=content_type,
    )
    return response["UploadId"]


MAX_MULTIPART_PARTS = 10000


async def generate_presigned_upload_urls(
    bucket: str, key: str, upload_id: str, num_parts: int
) -> list[str]:
    """Generate presigned URLs for each part of a multipart upload."""
    if num_parts < 1 or num_parts > MAX_MULTIPART_PARTS:
        raise ValueError(f"num_parts must be between 1 and {MAX_MULTIPART_PARTS}")
    client = _make_presign_client(bucket=bucket)
    urls = []
    for part_number in range(1, num_parts + 1):
        url = await _run_sync(
            client.generate_presigned_url,
            "upload_part",
            Params={
                "Bucket": bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=settings.PRESIGNED_URL_EXPIRY_SECONDS,
        )
        urls.append(url)
    return urls


async def complete_multipart_upload(
    bucket: str, key: str, upload_id: str, parts: list[dict]
) -> None:
    """Complete a multipart upload. parts = [{"PartNumber": 1, "ETag": "..."}]"""
    client = _make_client(bucket=bucket)
    await _run_sync(
        client.complete_multipart_upload,
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )
    invalidate_stats_cache(bucket)


async def abort_multipart_upload(bucket: str, key: str, upload_id: str) -> None:
    """Abort a multipart upload."""
    client = _make_client(bucket=bucket)
    await _run_sync(
        client.abort_multipart_upload,
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
    )


async def generate_presigned_download_url(bucket: str, key: str) -> str:
    """Generate a presigned download URL."""
    client = _make_presign_client(bucket=bucket)
    url = await _run_sync(
        client.generate_presigned_url,
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=settings.PRESIGNED_URL_EXPIRY_SECONDS,
    )
    return url


def _same_provider(bucket_a: str, bucket_b: str) -> bool:
    """Whether two buckets resolve to the same storage provider."""
    return _resolve_cfg(bucket=bucket_a)["id"] == _resolve_cfg(bucket=bucket_b)["id"]


async def copy_object(source_bucket: str, source_key: str, dest_bucket: str, dest_key: str) -> None:
    """Copy an object from source to destination.

    When source and destination live on the same provider, a server-side copy is
    used. Across providers, the object is streamed through s3BEAR (download from
    source, upload to destination)."""
    if _same_provider(source_bucket, dest_bucket):
        client = _make_client(bucket=dest_bucket)
        copy_source = {"Bucket": source_bucket, "Key": source_key}
        try:
            await _run_sync(client.copy_object, Bucket=dest_bucket, Key=dest_key, CopySource=copy_source)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"Source object not found: {source_key}")
            raise
        invalidate_stats_cache(dest_bucket)
        return

    # Cross-provider copy: pull the object from source, push it to destination.
    data, content_type = await get_object_bytes(source_bucket, source_key)
    await put_object(dest_bucket, dest_key, data, content_type=content_type)


async def move_object(source_bucket: str, source_key: str, dest_bucket: str, dest_key: str) -> None:
    """Move an object (copy + delete source)."""
    await copy_object(source_bucket, source_key, dest_bucket, dest_key)
    client = _make_client(bucket=source_bucket)
    await _run_sync(client.delete_object, Bucket=source_bucket, Key=source_key)
    invalidate_stats_cache(source_bucket)


def build_dest_key(source_key: str, dest_prefix: str) -> str:
    """Compute the destination key for a bulk copy/move: dest_prefix + basename.
    Pure helper (no I/O)."""
    basename = source_key.rstrip("/").split("/")[-1]
    if not basename:
        raise ValueError("source_key has no basename")
    if dest_prefix and not dest_prefix.endswith("/"):
        dest_prefix += "/"
    return f"{dest_prefix}{basename}"


async def bulk_copy_move(
    source_bucket: str,
    keys: list[str],
    dest_bucket: str,
    dest_prefix: str,
    *,
    move: bool = False,
) -> dict:
    """Copy (or move) many objects into dest_bucket under dest_prefix. Continues
    past per-object failures. Returns {"succeeded": [dest_key...], "errors": [{key, error}...]}."""
    succeeded: list[str] = []
    errors: list[dict] = []
    for key in keys:
        try:
            dest_key = build_dest_key(key, dest_prefix)
            if dest_bucket == source_bucket and dest_key == key:
                raise ValueError("source and destination are identical")
            if move:
                await move_object(source_bucket, key, dest_bucket, dest_key)
            else:
                await copy_object(source_bucket, key, dest_bucket, dest_key)
            succeeded.append(dest_key)
        except FileNotFoundError:
            errors.append({"key": key, "error": "source not found"})
        except Exception as e:  # noqa: BLE001 — collect and continue
            errors.append({"key": key, "error": str(e)})
    return {"succeeded": succeeded, "errors": errors}


async def get_object_metadata(bucket: str, key: str) -> dict:
    client = _make_client(bucket=bucket)
    try:
        response = await _run_sync(client.head_object, Bucket=bucket, Key=key)
        return {
            "content_type": response.get("ContentType", ""),
            "content_length": response.get("ContentLength", 0),
            "last_modified": response.get("LastModified"),
            "etag": response.get("ETag", "").strip('"'),
        }
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            raise FileNotFoundError(f"Object not found: {key}")
        raise
