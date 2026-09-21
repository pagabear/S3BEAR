<div align="center">

<img src="frontend/public/logo-wordmark-light.png" alt="s3BEAR" width="120" />

### Secure S3 Gateway for AI Workloads

**Serve images and files from private S3 storage to LLMs and browsers —
without ever making a bucket public.** One gateway enforces per-user permissions,
expiring links, and audit logging in front of any S3-compatible backend.

<br/>

[![Get Started](https://img.shields.io/badge/Get_Started-Quick_Start-2496ed?style=for-the-badge&logo=rocket&logoColor=white)](https://s3.pagabear.com/docs/quick-start/)
[![Watch Demo](https://img.shields.io/badge/Watch_Demo-▶-c72e49?style=for-the-badge)](#demo)
[![Images](https://img.shields.io/badge/Images-Docker_%26_Helm-2496ed?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/u/bearcomp)
[![Read the Docs](https://img.shields.io/badge/Read_the-Docs-009688?style=for-the-badge&logo=readthedocs&logoColor=white)](https://s3.pagabear.com)

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#license)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688.svg)](HOW-TO.md)
[![Frontend](https://img.shields.io/badge/frontend-React_18-61dafb.svg)](HOW-TO.md)
[![Images](https://img.shields.io/badge/images-Docker%20%7C%20Helm-2496ed.svg)](https://hub.docker.com/u/bearcomp)
[![Storage](https://img.shields.io/badge/storage-S3%20%2F%20MinIO-c72e49.svg)](HOW-TO.md)

</div>

---

## Demo

<div align="center">

<img src="assets/demo.gif" alt="s3BEAR demo" width="800" />

</div>

---

## The Problem

Multimodal LLMs (Claude, GPT-4o, Gemini) take images as **HTTPS URLs**. But your images
live in a **private** S3 bucket. So teams reach for bad options:

- **Make the bucket public** — now anything in it is exposed to the whole internet, forever.
- **Hand-roll presigned URLs** — scattered across scripts, no central control, hard to revoke, easy to leak.
- **Proxy through app code** — every service re-implements auth, MIME checks, and rate limits.

There is no single, governed door between your private storage and the outside world.

## The Solution

s3BEAR is that door. It sits in front of **any** S3-compatible backend (AWS S3, MinIO,
Ceph, Wasabi) and becomes the **only** access path. Storage stays private at the S3 level;
s3BEAR decides — per user, per link, per request — what gets out.

- **Mint an expiring, revocable HTTPS URL** for one object and pass it straight to an LLM API. It works while valid, then returns `410 Gone`. The bucket is never public.
- **Serve images to the browser** from private buckets with JWT permission checks and a MIME allow-list — no public exposure.
- **Resize on the fly** (`?w=1024&format=webp&q=80`) so you hand right-sized images to models instead of raw originals.
- Every request is **permission-checked, quota-limited, and audit-logged** in one place.

---

## Why s3BEAR

| | |
|---|---|
| **AI-ready URLs** | Turn any private object into a stable HTTPS URL an LLM can fetch — expiring, revocable, transformable. |
| **Private by default** | The S3 bucket is never made public. s3BEAR is the single gated access path; expired or revoked links return `410`. |
| **Central permissions + audit** | Group-based glob permissions (`marketing-*`) per action, per-bucket quotas, and an audit trail of every state-changing operation. |
| **Self-host anywhere** | One Docker command to try it; a Helm chart for production Kubernetes. Bring your own S3 or run embedded MinIO. |

Full capability list — multipart upload, bulk operations, scheduled cleanup, webhooks,
Azure Entra SSO, personal access tokens — is in **[HOW-TO.md](HOW-TO.md)**.

---

## Quick Start (60 seconds)

```bash
cp .env.example .env   # fill in your credentials
docker compose -f docker-compose.dev.yml up -d
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3100 |
| Backend API | http://localhost:8200 |
| MinIO Console | http://localhost:9001 |

Default admin: `admin@admin.com` / `admin` — **change this in production.**

Detailed setup, migrations, Kubernetes/Helm, and CORS: **[HOW-TO.md](HOW-TO.md)**.

---

## Screenshots

<table>
<tr>
<td width="50%"><b>Buckets</b><br/><img src="assets/screenshots/buckets.png" alt="Buckets" /></td>
<td width="50%"><b>Expiring share links</b><br/><img src="assets/screenshots/shares.png" alt="Share links" /></td>
</tr>
<tr>
<td width="50%"><b>Users & groups</b><br/><img src="assets/screenshots/users.png" alt="Users" /></td>
<td width="50%"><b>Audit log</b><br/><img src="assets/screenshots/audit.png" alt="Audit log" /></td>
</tr>
</table>

More screens (sign-in, storage & auth settings, webhooks) are in **[HOW-TO.md](HOW-TO.md)**.

---

## Performance

<!-- markdownlint-disable MD013 -->

Local development benchmarks cover direct object-store access, presigned
downloads, end-to-end authorization plus signing, and public share proxying.
Across 17 reports, all 2,680 measured samples completed successfully with no
short responses.

| Profile | Direct | Presigned data | Presigned E2E | Share proxy | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 16 MiB, c10, median of 3 | 1935 MiB/s | 1981 MiB/s | 1588 MiB/s | 1584 MiB/s | 0 / 360 |
| 1 MiB, c50 stress | 558 MiB/s | 475 MiB/s | 396 MiB/s | 161 MiB/s | 0 / 400 |

The ordinary presigned data path stays close to direct storage. Small public
share downloads remain the main high-concurrency bottleneck because they add
token accounting and proxy every byte through s3BEAR. These are same-host lab
results, not production capacity or vendor-ranking claims.

See **[benchmark results and gateway comparison](benchmarks/README.md)** for
methodology, p95 latency, success/failure criteria, raw-report interpretation,
and architectural comparisons with S3Proxy, VersityGW, and Ceph RGW.

<!-- markdownlint-enable MD013 -->

---

## Documentation

- **[Documentation](https://s3.pagabear.com)** — guides, configuration, deployment, and reference documentation
- **[HOW-TO.md](HOW-TO.md)** — architecture, API surface, configuration, and a feature-by-feature technical guide with real-world use cases

## License

MIT — see [LICENSE](LICENSE).
