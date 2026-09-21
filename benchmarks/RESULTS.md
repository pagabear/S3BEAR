# Local benchmark report: 2026-08-31

This report is a development baseline, not an industry ranking. It measures the
current s3BEAR architecture on one host and records enough context to reproduce
the experiment. Raw JSON reports live in `benchmarks/results/` and are ignored
by Git.

## Environment

- Source baseline: `ac5d635` on `main`, plus the performance changes described below
- Host: Apple M4 Mac mini, 10 cores, 16 GB RAM
- Runtime: Docker Engine 29.6.1, Docker Compose 5.3.0
- Stack: one backend process, PostgreSQL 16 Alpine, MinIO, benchmark client
- Network: Docker bridge on one host, HTTP without TLS
- Workload: 16 MiB object, 30 measured requests, concurrency 10, 3 warmups
- Repetition: initial baseline once; first optimization stage three times with medians reported

The local setup favors low latency and should not be used as a production
capacity promise. Production RTT, TLS, CPU limits, object-store disks, and
separate hosts will change the absolute numbers.

## 16 MiB / concurrency 10 results

| Path | Initial MiB/s | Stage-1 median MiB/s | Vs direct | p95 TTFB | Failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct object store | 1653 | 1700 | baseline | 12.7 ms | 0 |
| s3BEAR presigned data path | 1781 | 1783 | +4.9% | 11.0 ms | 0 |
| s3BEAR presigned E2E | 1034 | 1498 | -11.9% | 35.7 ms | 0 |
| s3BEAR share proxy | 480 | 1391 | -18.2% | 50.4 ms | 0 |

The positive presigned delta is normal run-order and local-host noise: both URLs
ultimately use the same MinIO data path. Across the three final runs there were
zero failures in 360 measured requests. Every final share-link counter recorded
exactly 33 accesses, including warmups.

Additional before/after signals:

| Signal | Initial | Final median | Change |
| --- | ---: | ---: | ---: |
| Share proxy throughput | 480 MiB/s | 1391 MiB/s | +190% |
| Share proxy p95 TTFB | 539 ms | 50 ms | -91% |
| Share proxy p95 total latency | 561 ms | 149 ms | -73% |
| Presigned E2E throughput | 1034 MiB/s | 1498 MiB/s | +45% |
| Presigned E2E control p95 | 119 ms | 28 ms | -76% |

## 1 MiB / concurrency 50 stress result

These three runs used the same fixture, 100 measured requests, 5 warmups, seed
`42`, and execution order. They isolate DB pool and counter contention changes.

| Configuration | Presigned E2E MiB/s | Control p95 | Share MiB/s | Share p95 TTFB |
| --- | ---: | ---: | ---: | ---: |
| 30 DB connections, one counter row | 254 | 262 ms | 160 | 564 ms |
| 64 DB connections, one counter row | 413 | 108 ms | 127 | 742 ms |
| 64 DB connections, 16 counter shards | 396 | 91 ms | 161 | 546 ms |

The larger DB pool removed a control-plane queue but initially made share-link
contention worse by allowing more transactions to wait on the same row. Sharded
counters retained the presign improvement while restoring share throughput and
reducing its p95 TTFB by 26% relative to the 64-connection hot-row run. The
sharded run recorded all 105 expected accesses across all 16 shards, and the
share-list API returned the same total.

The benchmark runner now randomizes target order and stores its seed and order
in each report. This reduces the systematic bias visible in the older fixed-order
runs while preserving reproducibility.

## Large-object smoke check

A separate 128 MiB, concurrency-5 run completed 10 measured requests per path
with zero errors. The share proxy delivered 1339 MiB/s versus 1412 MiB/s for
the direct path in that run, and all 11 share accesses including warmup were
recorded. Backend RSS was 161.8 MiB after the run, with no errors or connection
pool warnings in its log.

This was one stability run, not a repeated capacity result. The large positive
deltas on paths executed later show host cache and run-order effects, so only
the zero-error outcome and absence of obvious retained-memory growth should be
used as conclusions. Peak RSS needs a time-series collector during a longer
production-like campaign.

## Findings and fixes

1. Normal upload and download bytes do not pass through s3BEAR. The application
   authorizes the operation and returns presigned URLs, so its steady-state data
   path is effectively the direct object-store path.
2. A boto3 client was created for every operation. Runtime clients are now
   reused by provider, invalidated when provider configuration changes, and
   configured with a larger connection pool. One-off provider validation
   credentials remain uncached.
3. Share downloads read 64 KiB per thread-pool handoff. The default is now a
   configurable 1 MiB, and response bodies are closed on completion or client
   disconnect.
4. Each share request updated one database row and held that row lock until the
   full response finished streaming. Concurrent requests for the same link
   therefore queued before receiving bytes. Active-token validation and access
   accounting now run as one PostgreSQL CTE, with increments spread across 16
   counter shards. Existing historical counts remain part of API totals.
5. Authenticated-user group and permission loading used several eager-load
   round trips. JWT and PAT authentication now load the complete authorization
   graph with one joined query.
6. Multipart upload preparation scheduled and awaited one executor job per part.
   All signatures are now generated inside one executor job. A 1,000-part local
   microbenchmark improved from 183 ms to 92 ms, approximately 50%.
7. Database pool size and overflow are now deployment settings. Defaults remain
   `10+20`; the c50 lab profile uses `32+32`. The aggregate pool across all app
   replicas must stay below PostgreSQL's connection budget.

The remaining share-proxy gap is expected in this topology: each byte crosses
two HTTP connections and the Python application. For high-volume public
downloads, the preferred architecture is a short-lived signed redirect or CDN
offload when revocation requirements permit it. Keep the proxy route for flows
that must enforce per-request token state or transform content.

## External gateway comparison

No S3Proxy, VersityGW, Envoy, NGINX, or other external gateway endpoint was
available in this run, so no third-party performance number is claimed. The
runner accepts each product as `--target NAME=URL`; execute those targets from
the same client host, against the same object store and fixture, with matching
TLS, logging, caching, checksum, and resource settings.

Report these categories separately:

| Category | Candidate | Status |
| --- | --- | --- |
| Closest storage gateway | S3Proxy or VersityGW | Awaiting equivalent deployment URL |
| Proxy overhead lower bound | Envoy, NGINX, or HAProxy | Awaiting equivalent deployment URL |
| S3 frontend reference | MinIO, Ceph RGW, SeaweedFS, or Garage | Direct MinIO baseline measured; other stores require equivalent infrastructure |

Do not label an independent object store as faster or slower than s3BEAR without
accounting for its backing disks, replication, consistency, and durability. The
comparison command and full fairness checklist are in `benchmarks/README.md`.