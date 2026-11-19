# Stage 2 — Dixon-Coles mathematical engine

**Branch:** `repair/alea-3.0-end-to-end`  
**Date:** 19 November 2026

## Status: PASS

### Accepted

| Requirement | Evidence |
|-------------|----------|
| Full-distribution 1X2 (no grid renormalisation) | `exact_one_x_two` + `tests/test_stage2_exact_markets.py` |
| Full-distribution BTTS and over/under | same |
| Grid mass + explicit tail | `score_matrix` returns `(mat, tail)` |
| Invalid rates / rho rejected | parametrised invalid tests |
| Parity with production v2.4.1 closed-form markets | `tests/test_stage2_parity.py` |

### Notes

- Production predictor (v2.4.1) already documents exact Skellam + Dixon-Coles corrections for 1X2/BTTS/totals. Stage 2 is the independent, testable implementation of the same mathematics.
- Grid-conditional helpers (`one_x_two`, `btts`, `over_under`) remain available but are clearly labelled as conditional on the supplied grid. Prefer the `exact_*` functions for production scoring.

### Commands

```bash
python -m pytest tests/test_stage2_exact_markets.py tests/test_stage2_parity.py -q
```
