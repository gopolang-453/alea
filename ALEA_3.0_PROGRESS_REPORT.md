# ALEA 3.0 Development Report
**Date:** 18 November 2026  
**Scope:** Stages 0–5  
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
| 6–13 | Context, ML, calibration, backtesting, automation, UI, release | Not started | Require real data + comparative evaluation |

## What is proven
- Timestamp-aware data store (in-memory + SQLite) with snapshots that hide future information
- Dixon-Coles scoreline matrix, 1X2, BTTS, totals (probabilities sum correctly, rho=0 recovers Poisson)
- Leakage-safe Elo, form, H2H, rest
- Leakage-safe xG rolling features and overperformance
- Leakage-safe injuries, suspensions, confirmed lineups, position-aware impact stub

## What is not yet claimed
Comparative walk-forward evidence that any of the Stage 3–5 features improve predictions over the Dixon-Coles baseline. That requires a real historical dataset wired through the Stage 1 store.

## Next step
Connect a free results (+ optional xG) source and run leakage-safe comparative backtests. Retain only features that show improvement.

**Bottom line:** Stages 1–5 feature contracts are implemented and unit-tested. Code is on GitHub under `stages/`. No untested code was marked done.
