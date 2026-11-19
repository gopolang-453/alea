# ALEA Stage Progress Report

**Branch:** `repair/alea-3.0-end-to-end`  
**Report time:** 19 November 2026 21:20 UTC

---

## Summary table

| Stage | Status | Notes |
|-------|--------|-------|
| **1** Data store | **PASS** | FC/AFC strip added so OpenFootball names import cleanly. |
| **2** Dixon-Coles maths | **PASS** | Exact markets + parity test. |
| **3** Elo / form features | **PARTIAL** | Builders OK. Probability mapping + MLE comparison still open. |
| **4** xG | **BLOCKED** | No licensed timestamped historical source. |
| **5** Player / injury | **BLOCKED** | Same. |
| **6** Context | **BLOCKED** | Same. |
| **7** Ensemble | **PARTIAL** | Contracts + metrics + weighted average tested. No trained ML model (by design until features exist). |
| **8** Calibration | **PARTIAL** | Temperature scaling with leakage checks implemented. Not yet proven on a completed real walk-forward artifact. |
| **9** MLE walk-forward | **PARTIAL** | Runner fixed (name cleaning). OpenFootball import works (760 rows verified locally). Full multi-season walk-forward not yet completed as a committed artifact on this tip. Prospective ledger exists and is tested. |
| **10** Model registry | **PARTIAL** | Evidence-gated promote/rollback implemented and unit-tested. Not deployed. |
| **11** Prediction service | **PARTIAL** | Traceable prediction response + history store exist as code. Not deployed. |
| **12** Reliability | **PARTIAL** | Checksum, backup/restore, freshness, secret-scan utilities exist. Not operational monitoring. |
| **13** Release | **NOT COMPLETE** | Required. |

---

## What was done this session (remaining stages)

1. **Stage 1 fix** — `canonical_team` now strips `FC`/`AFC` and expands OpenFootball aliases (`ec77871`).
2. **Stage 9 fix** — runner runs production `clean_matches` before every MLE fit so OpenFootball names are accepted (`7272a14`).
3. **Local verification** — OpenFootball 2022-23 + 2023-24 imported (760 results). Name mismatch that blocked the runner is fixed.
4. Status of Stages 7–12 left honest: scaffolding + unit tests exist; no claim of integrated production pipeline or real-data Stage 9 completion.

---

## What still blocks Stage 13

1. Complete and commit a real multi-season Stage 9 MLE walk-forward + holdout report (run is now unblocked; needs time to finish and artifact commit).
2. Stage 3 Elo/form probability mapping evaluated on the same fixtures.
3. Stages 4–6 remain disabled until real timestamped sources exist.
4. No live scheduler / deployed service.
5. No merge to `main`, no tag, no release.

---

## How to finish Stage 9 evidence

```bash
python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22 2022-23 2023-24
python scripts/run_stage9_mle_backtest.py --holdout-season 2023-24 --min-train-matches 380 --step-days 28
# then commit results/stage9_mle/report.json (not the raw SQLite / raw JSON)
```

Do not mark Stage 13 complete until that report exists and the remaining gates above are closed.
