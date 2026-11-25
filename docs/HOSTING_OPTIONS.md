# Hosting options for the Stage 11 API (decision for the owner)

**Status: NOT DEPLOYED.** Nothing has been provisioned. Prices were checked on 24 Nov 2026 from the providers' own pages and change often.

## What the service needs

- **Workload:** a single read-only container (`Dockerfile`, Python WSGI on port 8080) serving one small SQLite file (under 1 MB today, growing by about 20 rows per run).
- **Refresh:** `ledger.sqlite` is refreshed after each Tuesday/Friday run by pulling the public `prospective-ledger` branch (or downloading the run artifact).
- **Security and operations:**
  - HTTPS.
  - A reverse proxy for rate limiting, because the built-in `wsgiref` server is single-threaded and not production-grade.
  - Optional authentication.
  - A health check on `/health`.
  - Log collection.
- **Backups:** the ledger is already backed up by git history and run artifacts, so the host holds only a disposable read-only copy.

## Comparison

| | Fly.io | Render | Railway | Hetzner Cloud VPS + Caddy | Google Cloud Run |
|---|---|---|---|---|---|
| Entry cost | `shared-cpu-1x` 256 MB at $2.19/month always-on; volumes $0.15/GB/month ([Fly.io pricing](https://docs.fly.io/about/pricing)) | $7/month for 0.5 CPU / 512 MB, never spins down; the free tier sleeps after 15 min and cannot attach disks; disks $0.25/GB/month ([Render Docker hosting](https://render.com/hosting/docker), [Render pricing](https://render-www.onrender.com/pricing)) | Hobby $5/month including $5 usage; volumes $0.15/GB/month, up to 5 GB ([Railway pricing docs](https://docs.railway.com/pricing)) | CX23 (2 vCPU, 4 GB) €5.99/month including IPv4, excluding VAT, but listed as "not available" at times in 2026 ([Hetzner cost-optimized](https://www.hetzner.com/cloud/cost-optimized/)) | Free tier of 180,000 vCPU-s, 360,000 GiB-s and 2 M requests/month on request-based billing ([Cloud Run pricing](https://cloud.google.com/run/pricing)) |
| Docker | Native (Machines from a Dockerfile) | Native | Native | You run Docker yourself | Native |
| Persistent storage | Local volumes; replication is your responsibility | Persistent disk, single instance | Volumes | Local disk | None persistent; bake the ledger into the image or fetch it at start |
| Refreshing the DB | Scheduled machine or `fly deploy` from CI | Redeploy hook from CI | Redeploy from CI | `cron` + `git pull` (simplest) | Rebuild/redeploy from CI after each run |
| HTTPS | Automatic | Automatic | Automatic | Caddy issues certificates automatically | Automatic |
| Authentication / rate limits | You add them (proxy or app) | You add them | You add them | Caddy/nginx rate limiting and basic auth | IAM or an API gateway |
| Backups | Volume snapshots (daily by default) | Disk snapshots | Volume backups | Provider backups at +20% | n/a (stateless) |
| Monitoring | Built-in metrics and logs | Built-in logs and metrics | Logs (7 days on Hobby) | You install it (e.g. an uptime check) | Cloud Monitoring/Logging |
| Reliability | No SLA on small plans | No SLA on Hobby | No SLA on Hobby | 99.9% per server, compensated in credits | Google SLA for Cloud Run |
| Operational complexity | Low to medium | Low | Low | Medium to high (OS patching, firewall, TLS) | Medium (GCP account, IAM, image registry) |

## Recommendation (the choice is yours)

The recommendation is **Fly.io with a small volume**, or the image-baked variant without a volume:

- It is the cheapest always-on Docker host here.
- It gives automatic HTTPS and a native health check.
- It can mount the ledger read-only.
- A GitHub Actions step after each successful ledger commit can redeploy or copy the new `ledger.sqlite`.

**Render** is the simplest alternative if you prefer a fixed $7/month price.

**Hetzner + Caddy** gives the most control per euro but needs server administration.

**Cloud Run** fits if you already use Google Cloud and accept rebuilding the image twice a week.

## Before any public deployment

1. **Licence decision.** Decide the licensing position for public outputs (`docs/DATA_SOURCES_AND_LICENSING.md`). Keep the `attribution` object in every response; it is already returned by the API.
2. **Reverse proxy.** Put a proxy (the platform's or Caddy) in front of the container, with rate limiting. Do not expose `wsgiref` directly.
3. **Port binding.** Bind the container to `127.0.0.1` behind the proxy on a VPS (`docker run -p 127.0.0.1:8080:8080 ...`). Mount the ledger read-only (`:ro`).
4. **Monitoring.** Add an external uptime monitor on `/health`. It returns 503 on a corrupt ledger, a hash mismatch or a foreign model version.
5. **Image pinning.** Pin the base image by digest and the GitHub Actions by SHA (currently tags only).
