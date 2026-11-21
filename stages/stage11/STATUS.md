# Stage 11 — Prediction Service

**Status (21 Nov 2026):** Wired and contract-tested end-to-end.

- `scripts/predict_cli.py` + `stages/stage11/prediction_service.py` exist and were exercised.
- Correctly refuses past-dated fixtures (information cutoff).
- Not deployed to a public endpoint; still local CLI only.
- Real EPL data path still requires internet + OpenFootball ingest.
