# Changelog

## 1.0.0: web app (unreleased, branch `feature/alea-web-app`)

Builds on ALEA 3.0 (PR #4). The champion model (`alea-dc-v2.4.1`, SHA-256 `4cfc6108…f022a`), its parameters, the registry, the 48 h–7 day window, the promotion rule (≥300 paired settled fixtures) and all existing ledger rows are unchanged.

### Added
- **Mobile web app** (`web/`, served at `/`): Matches, Match detail, Results and How it works screens. It works on phones, tablets and desktops, supports light and dark mode, and can be installed as a PWA shell (it does not work offline). No build step and no third-party requests. See `docs/WEB_APP.md`.
- **Forecast detail recorded at forecast time** (new forecasts only): the champion's expected goals (Poisson means) and the five most likely scorelines, taken from the frozen `predict()`. The run aborts without writing if `predict()`'s 1X2 differs from the published probabilities by more than 1e-6. Existing forecasts are not backfilled.
- **Fixture list:** each run writes `fixtures_upcoming.json` (OpenFootball, CC0, next 60 days) next to the ledger. The workflow commits it to the data branch.
- **API:** `GET /v1/fixtures/upcoming` (status per fixture: published, awaiting forecast or not forecast). Forecast objects now include `expected_goals`, `top_scorelines` and `prior_only`.
- **Hosted ledger sync** (`ALEA_LEDGER_SYNC_URL`): the server downloads the ledger from the public data branch and serves it only after the append-only gate passes. `/health` reports sync failures.
- **Security headers** on every response (strict CSP, nosniff, no-referrer, frame denial, COOP). Static files are served from an in-memory allowlist.
- `fly.toml` (Fly.io, not deployed), `docs/WEB_APP.md`, this changelog and `RELEASE_1.0_READINESS.md`.
- Tests: `tests/test_web_app.py` (32) and `tests/test_ledger_sync.py` (7). The CI container smoke test now also checks `/`, a static asset, path traversal and the fixtures endpoint.

### Changed
- The Dockerfile copies `web/` and creates a writable `/data` for the sync.
- `scripts/serve_api.py`: new options `ALEA_FIXTURES`, `ALEA_WEB_DIR`, `ALEA_LEDGER_SYNC_URL` and `ALEA_LEDGER_SYNC_MINUTES`.
- `docs/OPERATIONS.md`, `docs/HOSTING_OPTIONS.md` and `README.md` were updated for the web app, the sync and the recommended host.
