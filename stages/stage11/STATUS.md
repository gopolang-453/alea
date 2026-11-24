# Stage 11 — Prediction service

**Status (24 Nov 2026):** IMPLEMENTED AND TESTED. NOT DEPLOYED to a public host.

- `stages/stage11/api.py` (`ForecastAPI`, WSGI) is served by `scripts/serve_api.py` or by the `Dockerfile`. It is read-only over the prospective ledger.
- **Endpoints:**
  - `/health`
  - `/v1/status`
  - `/v1/predictions/upcoming`
  - `/v1/predictions/history`
  - `/v1/predictions/{fixture_key}`
  - `/v1/evaluation`
  - `/metrics`

  Each response carries H/D/A probabilities (checked to sum to 1), the model version, `predicted_at`, the training-data fingerprint and data freshness.
- **Never switches models silently.** It returns 503 if the ledger holds a model version other than the registered champion, if the champion file hash differs from `config/model_registry.json`, or if the ledger fails integrity.
- **Errors and logging:** input validation returns 400 with an error code and unknown keys return 404. Each request is logged as one JSON line with a request id, and Prometheus counters are exposed.
- **Tests:**
  - `tests/test_stage11_api.py` (20 tests: in-process and a real HTTP server).
  - The Stage 12 drill starts the HTTP server on the restored real ledger.
  - CI builds the container and checks a good ledger (200) and a corrupted one (503).
- `scripts/predict_cli.py` gives the same views on the command line. The old `prediction_service` reference was stale: that module never existed.
- **Missing:** a public deployment. Run and deploy instructions are in `docs/OPERATIONS.md`.
