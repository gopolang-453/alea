# Hosting the ALEA web app and API (decision for the owner)

**Status: NOT DEPLOYED.** Nothing has been provisioned. Prices were checked on 24–25 Nov 2026 from the providers' own pages and change often.

## Architecture (release 1.0)

```
GitHub Actions (Tue + Fri 06:00 UTC, from main)
  └─ runs the frozen champion, gates the ledger, commits ledger.sqlite + fixtures_upcoming.json
       to the public prospective-ledger branch
              │  (public https download, no credentials)
              ▼
One container (Dockerfile) on the host
  ├─ ledger sync thread: every 30 min download → append-only gate → atomic swap
  ├─ read-only API  /v1/...  /health  /metrics
  └─ web app        /   (HTML/CSS/JS, PWA shell)
              │  HTTPS (host's proxy terminates TLS)
              ▼
iPhone Safari / any browser  →  https://<app-name>.fly.dev  (or your own domain)
```

The host holds only a disposable copy. If it is lost, a restart downloads it again. A volume, deploy hook or GitHub token is not needed.

## What the service needs

- **Workload:** a single read-only container (`Dockerfile`, Python WSGI on port 8080) serving one small SQLite file (under 1 MB today, growing by about 20 rows per run).
- **Refresh:** built in. With `ALEA_LEDGER_SYNC_URL` set, the container pulls `ledger.sqlite` and `fixtures_upcoming.json` from the public `prospective-ledger` branch and swaps them in only after the append-only gate passes.
- **Security and operations:**
  - HTTPS.
  - A front proxy with a concurrency limit. The built-in server is a threaded `wsgiref` server, fine for a small personal site but not for heavy traffic. On Fly.io the platform proxy (`hard_limit` in `fly.toml`) provides this.
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
| Refreshing the DB | Built-in sync (no volume) | Built-in sync; the free tier sleeps, so the paid tier is needed | Built-in sync | Built-in sync | Built-in sync only while an instance is running; with scale-to-zero the first visit triggers a fresh download |
| HTTPS | Automatic | Automatic | Automatic | Caddy issues certificates automatically | Automatic |
| Authentication / rate limits | You add them (proxy or app) | You add them | You add them | Caddy/nginx rate limiting and basic auth | IAM or an API gateway |
| Backups | Volume snapshots (daily by default) | Disk snapshots | Volume backups | Provider backups at +20% | n/a (stateless) |
| Monitoring | Built-in metrics and logs | Built-in logs and metrics | Logs (7 days on Hobby) | You install it (e.g. an uptime check) | Cloud Monitoring/Logging |
| Reliability | No SLA on small plans | No SLA on Hobby | No SLA on Hobby | 99.9% per server, compensated in credits | Google SLA for Cloud Run |
| Operational complexity | Low to medium | Low | Low | Medium to high (OS patching, firewall, TLS) | Medium (GCP account, IAM, image registry) |

## Recommendation (the choice is yours)

**Fly.io, one `shared-cpu-1x` 256 MB machine, no volume: about $2.19/month.** ([Fly.io pricing](https://docs.fly.io/about/pricing))

- It is the cheapest always-on Docker host compared here, with automatic HTTPS on `<app>.fly.dev` and a health check on `/health`.
- It has a Johannesburg region (`jnb`) ([Fly.io regions](https://fly.io/docs/reference/regions/)).
- `fly.toml` in the repository is ready to use. No secrets are stored on the host.
- Fly needs an account with a payment card. A custom domain is optional and costs extra.

**Render** ($7/month, no sleep) is the simplest alternative. **Hetzner + Caddy** (€5.99/month) gives the most control but needs server administration. **Cloud Run** can be free at this traffic level, but needs a Google Cloud account and billing set up.

### Steps once you approve (needs your account)

1. Create a Fly.io account at https://fly.io and add a payment card (I cannot do this for you).
2. Install `flyctl`, run `fly auth login`, then from the repository root `fly launch --no-deploy --copy-config --name <unique-name>`, then `fly deploy`.
3. Open `https://<unique-name>.fly.dev` on the iPhone, then Share → Add to Home Screen.
4. Optional: point a domain you own at it with `fly certs add <domain>`.

## Before any public deployment

1. **Licence decision.** Decide the licensing position for public outputs (`docs/DATA_SOURCES_AND_LICENSING.md`). Keep the `attribution` object in every response; it is already returned by the API.
2. **Proxy.** Use the platform's proxy (Fly, Render, Railway, Cloud Run) or Caddy on a VPS, with a concurrency or rate limit. Do not expose the container port directly on a VPS.
3. **Port binding.** Bind the container to `127.0.0.1` behind the proxy on a VPS (`docker run -p 127.0.0.1:8080:8080 ...`). Either mount the ledger read-only (`:ro`) or use the built-in sync.
4. **Monitoring.** Add an external uptime monitor on `/health`. It returns 503 on a corrupt ledger, a hash mismatch or a foreign model version.
5. **Image pinning.** Pin the base image by digest and the GitHub Actions by SHA (currently tags only).
