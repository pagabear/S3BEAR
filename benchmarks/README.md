# s3BEAR performance benchmarks

<!-- markdownlint-disable MD013 -->

This suite measures the cost of inserting s3BEAR between a client and an
S3-compatible object store. It intentionally reports the control and data
planes separately because most s3BEAR transfers use presigned URLs and do not
proxy object bytes.

See the [detailed benchmark report](RESULTS.md) for the full optimization
history. Raw JSON reports are written under `benchmarks/results/` and are
ignored by Git.

## Measured results

The 17 available reports contain 2,680 measured target samples: 2,680
successful, zero failed, and zero short responses. Measurements were made on an
Apple M4 Mac mini with 10 cores and 16 GB RAM, using one s3BEAR process,
PostgreSQL 16, MinIO, Docker bridge networking, and HTTP without TLS.

Throughput cells below are `MiB/s (difference from direct in the same profile)`.
The 16 MiB row is the median of three repeated runs from the latest repeated
optimization stage. Other rows are single runs and should be read as smoke or
stress evidence, not capacity claims.

| Profile | Direct storage | Presigned data | Presigned E2E | Share proxy | Failed samples |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 MiB, c10 final smoke | 619.6 | 595.5 (-3.9%) | 285.0 (-54.0%) | 145.2 (-76.6%) | 0 / 80 |
| 16 MiB, c10, median of 3 | 1935.3 | 1980.9 (+2.4%) | 1588.1 (-17.9%) | 1583.9 (-18.2%) | 0 / 360 |
| 128 MiB, c5 stability run | 1411.7 | 1821.2 (+29.0%) | 1991.3 (+41.1%) | 1339.5 (-5.1%) | 0 / 40 |
| 1 MiB, c50 sharded stress | 558.3 | 475.2 (-14.9%) | 395.9 (-29.1%) | 160.6 (-71.2%) | 0 / 400 |

Positive deltas do not mean the gateway made MinIO faster. The 128 MiB run was
executed once with a fixed order, so host page cache and run order dominate the
positive values. The newer runner randomizes target order and records the seed.

### Optimization impact

The baseline is one 16 MiB/c10 run; optimized values are medians from three
runs. The comparison is directional because the older reports used a fixed
target order.

| Signal | Baseline | Optimized | Change |
| --- | ---: | ---: | ---: |
| Share throughput | 480.3 MiB/s | 1583.9 MiB/s | +229.7% |
| Share p95 TTFB | 539.3 ms | 40.1 ms | -92.6% |
| Share p95 total latency | 561.4 ms | 124.8 ms | -77.8% |
| Presigned E2E throughput | 1034.1 MiB/s | 1588.1 MiB/s | +53.6% |
| Presigned E2E control p95 | 118.5 ms | 18.2 ms | -84.7% |
| 1,000-part presign preparation | 183 ms | 92 ms | -49.8% |

### Success and failure scorecard

| Goal | Result | Evidence |
| --- | --- | --- |
| Correct, complete responses | **PASS** | 2,680 / 2,680 measured samples succeeded; no short response or error was recorded. |
| Presigned data path within 5% of direct | **PARTIAL** | Passed in final c10 smoke (-3.9%) and repeated 16 MiB stage (+2.4%); missed under c50 stress (-14.9%). |
| Presigned E2E control p95 below 100 ms at c50 | **PASS** | 91.0 ms after DB pool tuning and sharded counters, down from 262.4 ms. |
| Presigned E2E throughput within 10% of direct for objects >=16 MiB | **FAIL** | Repeated 16 MiB stage retained 82.1% of direct throughput, missing the target by 7.9 percentage points. |
| Large-object share stability | **PROVISIONAL PASS** | The 128 MiB run had zero failures and retained 94.9% of direct throughput, but it was only one run. |
| Small-object share performance at c50 | **FAIL** | Share retained 28.8% of direct throughput and p95 TTFB was 546.4 ms. PostgreSQL accounting and the double network hop remain visible. |
| Production capacity or cross-product ranking | **NOT MEASURED** | Tests used one host, HTTP, no resource limits, and no competitor endpoint. |

The main success is architectural: ordinary uploads and downloads use
presigned URLs, so object bytes bypass s3BEAR and remain close to the direct
storage path. The main remaining weakness is public share traffic with small
objects at high concurrency; every request still performs token/accounting work
and proxies every byte through the application.

## Download paths

| Path | Control plane | Data plane | What it answers |
| --- | --- | --- | --- |
| `direct` | Benchmark signs locally | Client to object store | Baseline without s3BEAR |
| `gateway-presigned` | One URL generated before the run | Client to object store | Whether the generated URL changes transfer performance |
| `gateway-presigned-e2e` | s3BEAR permission check and presign for every sample | Client to object store | User-visible cost of using s3BEAR |
| `gateway-share` | Share token resolved in PostgreSQL for every request | Object store to s3BEAR to client | Cost when every byte passes through s3BEAR |
| `--target NAME=URL` | Defined by the target | Target-defined | Comparison with another gateway or S3 frontend |

The report contains request rate, aggregate MiB/s, TTFB and total latency
distributions, failures, raw samples, and direct-baseline deltas. The E2E path
also reports a control-plane latency distribution. Target order is randomized
to reduce cache/run-order bias; the generated seed and execution order are
stored in every report. Pass `--seed` to reproduce an exact order.

## Quick start

The isolated stack uses ports `18200`, `19000`, and `19001`, avoiding the
normal development ports. Its credentials are fixed, local-only benchmark
credentials.

```bash
docker compose -f benchmarks/docker-compose.yml up -d --build backend

docker compose -f benchmarks/docker-compose.yml run --rm benchmark \
  python benchmarks/http_paths.py \
  --gateway-url http://backend:8000 \
  --s3-endpoint http://minio:9000 \
  --size-mib 16 \
  --requests 100 \
  --concurrency 10 \
  --warmup 5 \
  --output /results/16mib-c10.json
```

Run the focused runner tests with the same dependency image:

```bash
docker compose -f benchmarks/docker-compose.yml run --rm --no-deps benchmark \
  python -m unittest -v benchmarks.test_http_paths
```

Remove the isolated data after a campaign:

```bash
docker compose -f benchmarks/docker-compose.yml down --volumes
```

## Production target

The runner can also target an existing deployment. Keep secrets in environment
variables; they are not written to the JSON report.

```bash
export AWS_ACCESS_KEY_ID='...'
export AWS_SECRET_ACCESS_KEY='...'
export S3BEAR_BENCH_TOKEN='...'

python benchmarks/http_paths.py \
  --gateway-url https://s3bear.example.com \
  --s3-endpoint https://s3.example.com \
  --bucket s3bear-benchmark \
  --size-mib 128 \
  --requests 30 \
  --concurrency 10 \
  --output benchmarks/results/production-128mib-c10.json
```

Use a dedicated bucket and principal. The principal needs bucket read access,
and the runner needs object-store permission to create the bucket, upload the
fixture, inspect it, and generate the direct presigned URL. Use
`--skip-prepare` when the exact-size fixture already exists.

## Test matrix

Run every case at least three times with different generated seeds and compare
medians. A practical first campaign is:

| Object size | Concurrency | Requests per run | Dominant signal |
| ---: | ---: | ---: | --- |
| 1 MiB | 1, 10, 50 | 300 | Control plane, TTFB, request rate |
| 16 MiB | 1, 10, 50 | 100 | Typical transfer and concurrency |
| 128 MiB | 1, 10, 25 | 30 | Sustained throughput and backpressure |
| 1024 MiB | 1, 4 | 5 | Long-stream stability and memory |

Record s3BEAR commit, gateway/product version, CPU and memory limits, TLS mode,
network placement, object-store version, and whether caches are warm. Do not
compare runs with different durability, encryption, checksum, logging, or TLS
settings. Monitor client, s3BEAR, PostgreSQL, and object-store CPU, RSS, network
bytes, open connections, and disk I/O during each run.

Database concurrency is deployment-specific. The isolated benchmark profile
uses `DB_POOL_SIZE=32` and `DB_MAX_OVERFLOW=32`; production must keep the sum of
all replica pools below PostgreSQL's connection budget. The application defaults
remain the conservative `10+20`.

## Comparable S3 gateways

No competitor was executed by this benchmark, so the table compares
architecture and measurement scope, not vendor throughput. Published numbers
from different hardware, storage, durability, or TLS settings are not included.

| Product or path | Official role and backing storage | Do object bytes traverse it? | Closest s3BEAR path | Measured here |
| --- | --- | --- | --- | --- |
| s3BEAR presigned | Authorization, management, and URL signing in front of an S3-compatible store | No, after URL creation | `gateway-presigned-e2e` | Yes |
| s3BEAR public share | Token validation, access accounting, and streaming from the S3-compatible store | Yes | `gateway-share` | Yes |
| [S3Proxy](https://github.com/gaul/s3proxy) | Java/jclouds S3 API proxy and protocol translation for S3, Azure Blob, GCS, Swift, SFTP, or filesystem backends | Normally yes; some backend-native operations can avoid transfer | Public share data path, but with a broader S3 translation role | No |
| [VersityGW](https://github.com/versity/versitygw) | Stateless Go S3 translation service for POSIX, ScoutFS, Azure Blob, or another S3 server | Yes for normal object traffic | Full inline gateway; closest external data-path comparison | No |
| [Ceph RGW](https://docs.ceph.com/en/latest/radosgw/) | S3/Swift HTTP gateway integrated directly with a Ceph cluster through `librados` | Yes, through RGW into Ceph | Infrastructure reference, not equivalent middleware over MinIO | No |

S3Proxy and VersityGW are the most useful external comparisons when both are
configured against the same backing S3 store as s3BEAR. Ceph RGW should be
reported separately because changing to Ceph also changes the storage engine,
data layout, durability path, and caching behavior.

Create or obtain a signed/public URL for the same-size object and add it as a
target. The URL may contain `=` characters.

```bash
python benchmarks/http_paths.py \
  --paths direct,gateway-presigned,gateway-presigned-e2e,gateway-share \
  --target s3proxy='https://gateway.example/bench/16mib.bin?...' \
  --target envoy='https://proxy.example/bench/16mib.bin?...'
```

Static external URLs measure the data path. If another product has a separate
authorization or signing API, measure that API independently or add an adapter
that performs its control request for every sample, as
`gateway-presigned-e2e` does for s3BEAR.

For a valid numeric product comparison, keep the client host, object bytes,
backing store, TLS mode, CPU/memory limits, checksums, logging, warmup, request
count, concurrency, and target-order seed identical. Until those target reports
exist, this README deliberately makes no claim that s3BEAR is faster or slower
than S3Proxy or VersityGW.

## Reading the result

Initial regression guardrails for a same-host lab are:

- zero failed or short responses;
- `gateway-presigned` aggregate throughput within 5% of `direct`;
- E2E control-plane p95 below 100 ms;
- for objects at least 16 MiB, E2E throughput within 10% of `direct`;
- stable proxy throughput and memory as concurrency rises, with no growing
  latency tail.

These are engineering starting points, not universal SLAs. Production budgets
must reflect network RTT, object-store latency, hardware, and expected object
sizes.

Use the metric pattern to choose the next change:

| Signal | Likely area | Candidate changes |
| --- | --- | --- |
| Presigned transfer differs from direct | DNS, TLS, URL host/style, storage routing | Make both URLs traverse the same network and TLS path; inspect redirects and signatures |
| E2E control time is high | Authentication, permission lookup, boto client construction, DB pool | Reuse S3 clients, profile DB queries, size pools, cache stable authorization data |
| Share TTFB is high | Token lookup, access-counter row lock, first object-store read | Check indexes and transaction duration; keep write locks out of the response stream |
| Share throughput falls with object size | Proxy stream loop, chunk size, thread pool, double network hop | Increase measured chunk size, remove per-chunk executor work, use redirect/offload or CDN where policy permits |
| Errors appear only at concurrency | Worker, thread, DB, socket, or file-descriptor limits | Inspect saturation metrics, then tune one constrained pool at a time |

Re-run the identical matrix after each change. Keep raw reports so an apparent
throughput gain cannot hide worse p95/p99 latency or errors.

<!-- markdownlint-enable MD013 -->