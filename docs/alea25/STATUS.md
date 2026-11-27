# ALEA 2.5 Status

**Branch:** `dev/alea-2.5-improvements`  
**Date:** 2026-11-27  
**Champion (unchanged):** `alea-dc-v2.4.1`  
**SHA-256:** `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`

## Implemented in this milestone

| Component | Path | Status |
|-----------|------|--------|
| Parameter grid (ξ, reg) | `experiments/alea25/parameter_grid.py` | Implemented |
| Extended calibration + reliability diagrams | `experiments/alea25/calibration_ext.py` | Implemented |
| Block-bootstrap CI | `experiments/alea25/bootstrap.py` | Implemented |
| Experiment runner | `experiments/alea25/run_experiments.py` | Implemented |
| Unit tests | `tests/experiments/test_alea25_*.py` | Implemented |
| Research notes | `docs/alea25/RESEARCH_NOTES.md` | Written |

## Explicitly protected

- `alea_predictor_v2_4_1.py` – not modified, SHA verified before any experiment.
- Prospective ledger (`prospective-ledger` branch) – never written to.
- Git history – no force-push, no odds-history cleanup.
- Model registry champion entry – unchanged.

## How to run (development only)

```bash
# Smoke test with synthetic data
python -m experiments.alea25.run_experiments --synthetic --quick --out results/alea25/smoke.json

# Unit tests
python -m pytest tests/experiments/ -q

# Full grid (requires a local matches CSV compatible with the champion loader)
python -m experiments.alea25.run_experiments --data path/to/matches.csv --out results/alea25/full_grid.json
```

## Remaining blockers / limitations

1. **Real-data walk-forward** of the full ξ/reg grid needs the OpenFootball persistent store (or an equivalent local CSV). The runner supports CSV input; the synthetic path is for CI smoke only.
2. **xG / player / injury features** remain blocked by the licensing and timestamp requirements documented in `docs/DATA_SOURCES_AND_LICENSING.md`.
3. **Prospective sample size** is still far below the 300-fixture promotion threshold. No experimental model is eligible for promotion.
4. **Public hosting** of the web app / API is an owner decision and is outside the scope of the mathematical experiments.

## Recommendation

Continue collecting prospective forecasts under the frozen champion. Once ≥300 settled paired fixtures exist, re-evaluate the strongest 2.5 candidates under the registered promotion rule. Until then, keep all experimental models on this development branch only.
