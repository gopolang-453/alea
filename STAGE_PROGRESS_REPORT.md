# ALEA Stage Progress Report

**Branch:** `repair/alea-3.0-end-to-end`  
**Report time:** 19 November 2026 21:08 UTC  
**Latest commits this session:**
- `9d0af7ae` — Stage 1 acceptance documentation
- `b762c3f8` — Stage 2 parity test vs production
- `025eb954` — Stage 2 STATUS
- `50ab608f` — Stage 3 STATUS (PARTIAL)
- `345ea611` — Stage 4 STATUS clarified

---

## Summary table

| Stage | Status | Notes |
|-------|--------|-------|
| **1** Data store | **PASS** | Persistent, idempotent, conservative availability, feature records, OpenFootball atomic import. Evidence in `stages/stage1/STATUS.md` + tests. |
| **2** Dixon-Coles maths | **PASS** | Exact full-distribution 1X2/BTTS/totals + parity test against production closed-form path. |
| **3** Elo / form features | **PARTIAL** | Feature builders + temporal safety PASS. Probability mapping + evaluation vs MLE still open (needs Stage 9). |
| **4** xG | **BLOCKED** | Calculators exist; no licensed timestamped historical source → not evaluated. |
| **5** Player / injury | **BLOCKED** | Same external-data limitation. |
| **6** Context | **BLOCKED** | Same external-data limitation. |
| **7** Ensemble / trained models | **NOT DONE** | Safety scaffolding exists; no trained model or weight learning on real data. |
| **8** Calibration | **NOT DONE** | Temperature code exists; not yet proven on later out-of-sample data from a real walk-forward. |
| **9** Full MLE walk-forward + prospective scoring | **NOT DONE** | Runner + prospective ledger exist. Real OpenFootball import + development/holdout run has not been executed and reported on this branch tip. |
| **10–12** Registry / prediction service / reliability | **PARTIAL** | Code + unit tests exist. Not an integrated running pipeline. |
| **13** Release | **NOT COMPLETE** | As required. |

---

## What was actually pushed this session

1. Stage 1 formal acceptance document (`stages/stage1/STATUS.md`).
2. Stage 2 parity test (`tests/test_stage2_parity.py`) and acceptance document.
3. Stage 3 honest PARTIAL status (features ok, evaluation still open).
4. Stage 4 status clarified as evaluation-blocked.

No merge to `main`. No release. No invented xG/injury data.

---

## Recommended next actions (in order)

1. **Run Stage 9 real-data path**  
   ```bash
   python scripts/fetch_openfootball.py
   python scripts/run_stage9_mle_backtest.py --holdout-season 2023-24
   ```
   Then commit the report artifact (not the raw data) and update Stage 9 STATUS.

2. **Stage 3 probability mapping + evaluation** on the same fixtures as the Stage 9 MLE run.

3. Only after that: Stage 7/8 evidence, then 10–12 integration, then Stage 13 checklist.

---

## Hard rules still in force

- `alea_predictor_v2_4_1.py` stays frozen.
- No betting / staking.
- Stages 4–6 stay disabled for prediction until real timestamped sources exist.
- Stage 13 stays open until real-data evidence and operational checks pass.
