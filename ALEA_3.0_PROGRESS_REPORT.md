# ALEA 3.0 Development Report
**Date:** 18 November 2026  
**Scope of this sitting:** Stage 0 (prior) + Stages 1–3  
**Rule followed:** No stage marked complete without green tests.

---

## Summary

| Stage | Title | Status | Tests |
|-------|--------|--------|-------|
| 0 | Audit existing ALEA | Complete (prior session) | Manual inspection of repo |
| 1 | Data collection & management | **Core complete** | 13 passed |
| 2 | Dixon-Coles mathematical engine | **Complete** | 9 passed |
| 3 | Team strength, form and ratings | **Feature layer complete** | 8 passed |
| 4–13 | xG, players, ML, backtesting, automation, UI, release | Not started | Require real data and comparative evaluation |

---

## Stage 1 — Data management

**Files**
- `stages/stage1/data_store.py`
- `stages/stage1/persistent_store.py`
- `stages/stage1/tests/test_stage1_data.py`
- `stages/stage1/tests/test_stage1_persistent.py`

**Proven by tests**
- Canonical team identity
- Explicit `available_at` timestamps
- Snapshots hide future information
- Duplicate detection and future-result rejection
- Fail-closed xG / injury stubs
- SQLite persistence and recovery (identical fingerprint after reopen)
- CSV ingest compatible with existing ALEA schema

**13 tests passed**

---

## Stage 2 — Dixon-Coles mathematics

**Files**
- `stages/stage2/dixon_coles.py`
- `stages/stage2/tests/test_stage2_math.py`

**Proven by tests**
- Scoreline matrix sums to 1 − tail
- rho = 0 recovers independent Poisson
- Home/away reversal is the transpose
- Extreme rates remain non-negative
- Unsafe rho rejected
- 1X2, BTTS, over/under coherent with the same matrix

**9 tests passed**

---

## Stage 3 — Team strength, form and ratings

**Files**
- `stages/stage3/features.py`
- `stages/stage3/tests/test_stage3_features.py`

**Proven by tests**
- Elo updates only on matches available before the cutoff
- Recent form (points, goals, PPG) with home/away filter respects as_of
- Weighted H2H excludes future meetings and applies decay
- Rest days and matches-in-window are leakage-safe

**8 tests passed**

**Not yet claimed**  
Comparative backtests showing that Elo, form, H2H or congestion improve predictions over Dixon-Coles alone. Those require a real historical dataset and are left for the next sitting.

---

## Why later stages were not started

Stages 4+ need real feature data (xG, injuries, lineups) and leakage-safe comparative evaluation against the current model. Adding them without that evidence would violate the roadmap.

---

## Recommendation for the next sitting

1. Wire a free results source through the Stage 1 store.
2. Run a walk-forward comparison of the Stage 3 features against the Dixon-Coles baseline.
3. Retain only the features that show improvement.

---

**Bottom line:** Stages 1–3 are implemented and unit-tested. The code is ready for comparative evaluation once a real data source is connected. No untested code was marked done.
