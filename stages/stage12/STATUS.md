# Stage 12 — Reliability / Security

**Status (24 Nov 2026):** Recovery drill implemented and passing; not deployed.

- `scripts/recovery_drill.py` (tested by `tests/test_stage12_recovery_drill.py`) runs six checks on scratch copies of the frozen baseline: source integrity, verified backup, corruption detected, restore from a corrupted backup refused, restore from the good backup, restored integrity. Latest run: 6/6 pass. The script was cited here earlier but did not exist until 24 Nov 2026.
- `data_freshness` gates the live forecast script (`scripts/run_prospective_forecast.py`).
- Secret scan: `scripts/security_check.py` passes.
- Not yet run against a real production store; no continuous monitoring is deployed.
