# ALEA operations guide

Commands are run from the repository root. Python 3.11 is tested in CI; 3.14 has also been used locally.

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt      # runtime: numpy, pandas, scipy, requests
sha256sum -c SHA256SUMS.txt              # frozen champion and baselines must be OK
```

## Configuration

ALEA needs **no API keys or credentials**. Every source it uses is public and licensed (see `docs/DATA_SOURCES_AND_LICENSING.md`). If a keyed source is ever added, read the key from an environment variable or a GitHub Actions secret, never from source or logs. `scripts/security_check.py` fails CI on high-confidence secret patterns.

| Setting | Where | Default |
|---|---|---|
| Champion, challengers, promotion rule | `config/model_registry.json` (change only by reviewed commit) | v2.4.1, xi 0.0018, reg 1.0 |
| Ledger path | `--ledger` / `ALEA_LEDGER` | `results/prospective/ledger.sqlite` (frozen seed copy). The live ledger is on branch `prospective-ledger` |
| Forecast window | `--horizon-days`, `--min-lead-hours` | 7 days, 48 h |
| Settlement grace | `--grace-hours` | 60 h after expected full time |
| Freshness limit | `--max-age-hours` | 240 h |
| API | `ALEA_HOST`, `ALEA_PORT`, `ALEA_MAX_STALENESS_HOURS`, `ALEA_LOG_FILE`, `ALEA_REGISTRY` | 127.0.0.1, 8080, 216 h |

## Run the tests

```bash
python -m pytest -q                      # full suite (~20 min; walk-forward tests dominate)
python tests/run_all.py                  # v2.4.1 suite runner
python dev/tests/test_dev_repairs.py
python scripts/security_check.py
python scripts/recovery_drill.py         # artifact drill
python scripts/recovery_drill.py --ledger results/prospective/ledger.sqlite   # ledger + service drill
```

## Import history

```bash
python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26
curl -fsS -o data/raw/live/of_2026-27.json \
  https://raw.githubusercontent.com/openfootball/football.json/master/2026-27/en.1.json
```

Raw files stay under `data/` (gitignored).

## Generate predictions

```bash
python scripts/run_prospective_forecast.py --fetch-wikipedia \
  --ledger ledger-data/ledger.sqlite --output-dir ledger-data
```

**What a run does:**

1. Verifies the champion hash.
2. Fetches the Wikipedia revision.
3. Validates the fixtures, team names, completeness, cross-source agreement and freshness.
4. Settles finished fixtures.
5. Refits the champion on the data available before the run.
6. Appends forecasts for fixtures between 48 h and 7 days ahead.
7. Writes `report.md`, `evaluation.json`, `runs/run_*.json`, `runs/forecasts_*.csv`, `runs/report_*.md` and `logs/run_*.log`.

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | blocked by a data gate. Nothing was forecast and the reason is logged |
| 3 | ledger missing, corrupt or failing integrity. The ledger is never auto-created; pass `--init-ledger` only for a brand-new ledger |
| 1 | unexpected error |

**Safety:**

- Re-running is safe: existing forecasts are kept and nothing is duplicated.
- Pass `--crosscheck-csv data/raw/live/fd_2627_E0.csv` for an extra local football-data check. This is for personal use only, so do not commit or upload that file.
- `python scripts/predict_cli.py upcoming|history|fixture KEY|health` shows the frozen forecasts with the same logic as the API. It never fits a model or writes to the ledger.

## Schedule

`.github/workflows/weekly-prospective-forecast.yml` runs Tuesday and Friday at 06:00 UTC, and on demand (`workflow_dispatch`, optionally `dry_run`). Each run:

- checks out the code and the data branch `prospective-ledger`, which holds the live `ledger.sqlite` and its reports, so it never touches `main`;
- runs the pipeline, then the Stage 12 drill and the API smoke test against that ledger;
- commits the ledger and reports to the data branch;
- uploads the reports, logs and a verified backup as a 90-day artifact.

Failures are not hidden: any non-zero step writes a job summary, opens or updates the issue "ALEA prospective run failing", and fails the job.

- **Schedules and manual runs only work from the default branch.** Until the workflow is merged to `main`, it runs once whenever the workflow file changes on a `repair/**` branch. After merge, start it manually with `gh workflow run weekly-prospective-forecast.yml`.
- **One writer.** The `concurrency` group allows a single writer, and a run in progress is never cancelled.

## Inspect history

```bash
python scripts/ledger_admin.py --ledger ledger-data/ledger.sqlite status      # every forecast and its status
python scripts/ledger_admin.py --ledger ledger-data/ledger.sqlite integrity
python scripts/ledger_admin.py --ledger ledger-data/ledger.sqlite issues      # data-quality log
```

The API endpoints listed in the next section give the same views.

## Run the API

```bash
python scripts/serve_api.py --ledger ledger-data/ledger.sqlite --port 8080
# or
docker build -t alea-api . && docker run --rm -p 8080:8080 -v "$PWD/ledger-data:/data:ro" alea-api
```

| Endpoint | Returns |
|---|---|
| `GET /health` | `ok` / `degraded` (stale data, warnings) with HTTP 200, or `unhealthy` with HTTP 503 (ledger missing/corrupt, champion hash mismatch, foreign model version) |
| `GET /v1/status` | champion, registry, ledger fingerprint, freshness, last run |
| `GET /v1/predictions/upcoming?days=1..60&include_challengers=true` | pending champion forecasts with H/D/A probabilities (sum to 1), model version, timestamps, data freshness |
| `GET /v1/predictions/history?team=&from=&to=&status=&limit=1..500&offset=` | all forecasts with status and outcome |
| `GET /v1/predictions/{fixture_key}` | one forecast (URL-encoded key) with status, fixture events and challenger forecasts |
| `GET /v1/evaluation` | the prospective evaluation (metrics, CIs, sample sizes) |
| `GET /metrics` | request counters (Prometheus text) |

**Behaviour:**

- Invalid parameters return a 400 JSON error with a `code`.
- Every request is logged as one JSON line with a request id.
- The API is read-only, and it never switches models: if the ledger contains a model version other than the registered champion, it refuses with a 503.

**Deployment:** any host that can run the container and mount the ledger read-only will do. To refresh, pull the `prospective-ledger` branch periodically (for example with a cron `git pull`). The service has not been deployed to a public host; see the checklist.

## Back up and restore

```bash
python scripts/ledger_admin.py --ledger ledger-data/ledger.sqlite backup --dir backups/
python scripts/ledger_admin.py --ledger ledger-data/ledger.sqlite restore backups/ledger_<stamp>_<sha>.sqlite
```

**Backup:**

- It uses SQLite's online backup API, so it is consistent even while a writer is active.
- It writes `<file>.manifest.json` with the SHA-256, the forecast fingerprint and the fixture keys.

**Restore:**

- It verifies the hash, `PRAGMA integrity_check` and the fingerprint, then replaces the file atomically. The replaced file is kept as `*.pre-restore-<stamp>`.
- It refuses a backup that lacks forecasts present in the current ledger. `--allow-history-loss` overrides this; it is a last resort.
- Every scheduled run also uploads a verified backup as an artifact, and the data branch's git history is itself a full backup.

## Recovery

| Symptom | Action |
|---|---|
| Exit 2, "results feed incomplete" | Check Wikipedia. If the match was postponed, `ledger_admin.py event KEY POSTPONED --source "<statement URL>"`. If it was rescheduled, add `RESCHEDULED --new-kickoff <ISO>`. Re-run. |
| Exit 2, "feeds disagree" / conflict in the report | Verify the score from an official source, then `ledger_admin.py correct KEY H A --reason "<evidence>" --operator <name>`. Check the Wikipedia history for vandalism. |
| Exit 2, "team names inconsistent" | Add the alias in `stages/stage1/data_store.py::canonical_team`, add a test, and commit. Do not edit the ledger. |
| Exit 2, "stale" | Wikipedia has not been updated. Wait and re-run with `workflow_dispatch`. Do not lower `--max-age-hours` to force a run. |
| Exit 3, ledger missing/corrupt | Do not use `--init-ledger`. Restore the latest backup (artifact or `git log` on `prospective-ledger`) with `ledger_admin.py restore`, run `ledger_admin.py integrity`, then re-run. Forecasts already in the backup are not duplicated. |
| Champion hash mismatch | Someone changed `alea_predictor_v2_4_1.py`. Revert it; never update the registry hash to match. |
| Forecast for a match that kicked off early | `ledger_admin.py event KEY VOID --source "<evidence>" --detail "played before forecast"`. The row stays but is excluded. |
| Workflow interrupted mid-run | SQLite transactions roll back (exercised by the drill). Re-run; the run is idempotent. |

## Release

See `RELEASE_READINESS_CHECKLIST.md`. Do not tag v3.0.0 while any row is still blocked.
