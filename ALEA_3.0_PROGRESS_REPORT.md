# ALEA 3.0 Development Report
**Date:** 18 November 2026  
**Scope:** Stages 0–7  
**Rule:** No stage marked complete without green tests.

## Summary

| Stage | Title | Status | Tests |
|-------|--------|--------|-------|
| 0 | Audit existing ALEA | Complete | Manual inspection |
| 1 | Data collection & management | Core complete | 13 passed |
| 2 | Dixon-Coles mathematical engine | Complete | 9 passed |
| 3 | Team strength, form and ratings | Feature layer complete | 8 passed |
| 4 | Expected goals (xG) | Feature layer complete | 5 passed |
| 5 | Player intelligence, injuries, suspensions | Feature layer complete | 6 passed |
| 6 | Advanced contextual factors | Feature contracts complete | 4 passed |
| 7 | Machine learning and ensemble | Contracts complete | 7 passed |
| 8–13 | Calibration, backtesting, automation, UI, reliability, release | Not started | Require real data + comparative evaluation |

## What is proven
- Timestamp-aware data store with snapshots
- Dixon-Coles mathematics (scoreline matrix, 1X2, BTTS, totals)
- Leakage-safe Elo, form, H2H, rest
- Leakage-safe xG features
- Leakage-safe injuries, suspensions, lineups, impact stub
- Contextual feature contracts (weather, referee, manager, travel, derby)
- Ensemble scaffolding (log loss, Brier, weighted average, best-model selection)

## What is not yet claimed
Comparative walk-forward evidence that any Stage 3–7 component improves predictions over the Dixon-Coles baseline. Training of actual ML models is also not done.

## Next step
Wire a real historical results source through the Stage 1 store and run leakage-safe comparative backtests. Retain only what improves the baseline.

**Bottom line:** Stages 1–7 contracts are implemented and unit-tested. Code is on GitHub under `stages/`. No untested code was marked done.
