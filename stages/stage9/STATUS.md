# Stage 9 — Walk-forward evaluation

## Status: REAL-DATA EVIDENCE OBTAINED (PARTIAL acceptance)

### Passed

- OpenFootball import → Stage 1 store → production MLE expanding-window runner
- Untouched 2023-24 holdout (380 matches)
- Model beats training-rate and uniform baselines on log loss, Brier, RPS, accuracy
- Prospective ledger contracts tested separately

**Evidence:** `results/stage9_mle/REPORT.md` (2026-11-20 run)

Holdout headline: log loss **0.943**, accuracy **57.9%** vs rate baseline log loss 1.054 / accuracy 46.1%.

### Still open

- Elo/form (Stage 3) not yet scored on the same 380 holdout fixtures
- Temperature calibration (Stage 8) not fitted on development predictions from this run
- No market/odds benchmark (licence + timestamp constraint)
- Five-season (2019–24) full run optional; three-season evidence is already informative

### Decision rule

Stage 9 core protocol is no longer blocked. Feature and calibration candidates must beat **this** holdout baseline on identical fixtures before promotion.
