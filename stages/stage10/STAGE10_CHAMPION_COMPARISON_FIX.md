# Stage 10 Champion Comparison Fix

**Date:** 21 November 2026

## Problem identified

The original Stage 10 automation compared a candidate model against a *generic baseline*
rather than against the *currently registered champion* on identical fixtures and cutoffs.
That is the wrong gate: a candidate can look good vs a weak baseline and still be worse
than the live champion.

## Fix

`stages/stage10/champion_comparison.py` now:

1. Loads the registered champion from the ModelRegistry.
2. Evaluates both champion and candidate on the **same** holdout fixtures with the
   **same** information cutoffs.
3. Only allows promotion when the candidate improves primary metric (log loss) without
   material degradation on secondary metrics (Brier / RPS / calibration).
4. Records both sides of the comparison for audit.

## Evidence from this session (synthetic data, no internet)

### Scenario A — correct rejection
- Champion already registered.
- Candidate trained on identical data → identical holdout log loss.
- Gate correctly refused promotion. Champion left untouched. Candidate stored for audit only.

### Scenario B — correct promotion
- No champion (or weaker champion).
- Candidate produced better holdout log loss.
- Gate promoted; registry updated; SHA-256 verified.

Both scenarios were executed end-to-end through `scripts/refresh_and_retrain.py`.

## Regression test

`tests/test_stage10_champion_comparison.py` was added. It was verified by direct
execution (pytest not available in the offline sandbox used for this pass).

## Remaining limitations (honest)

- Still synthetic data only; not yet run on real EPL fixtures.
- Live scheduling and fixture feed remain open (Stage 10.1 / environment).
- Stage 13 release gate stays open until real-data promotion is demonstrated.
