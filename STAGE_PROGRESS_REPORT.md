# ALEA Stage Progress Report

**Branch:** `repair/alea-3.0-end-to-end`  
**Report time:** 20 November 2026 11:35 UTC

---

## Summary table

| Stage | Status | Notes |
|-------|--------|-------|
| **1** Data store | **PASS** | FC/AFC strip; OpenFootball import verified. |
| **2** Dixon-Coles maths | **PASS** | Exact markets + parity; frozen v2.4.1. |
| **3** Elo / form | **PARTIAL** | Features OK. Elo & DC+Elo **rejected** on holdout. |
| **4** xG | **BLOCKED** | No licensed timestamped source. |
| **5** Player / injury | **BLOCKED** | Same. |
| **6** Context | **BLOCKED** | Same. |
| **7** Ensemble | **PARTIAL** | Contracts tested; equal DC+Elo did not beat champion. |
| **8** Calibration | **PARTIAL** | Temperature fit on development; **rejected** on holdout. |
| **9** MLE walk-forward | **PASS (core)** | 2023-24 holdout LL **0.943**, Acc **57.9%**. |
| **10** Model registry | **PARTIAL** | Unit-tested; not deployed. |
| **11** Prediction service | **PARTIAL** | Contracts exist; not deployed. |
| **12** Reliability | **PARTIAL** | Unit-tested utilities. |
| **13** Release | **NOT COMPLETE** | Scope decision required. |

---

## Execution evidence (this session)

- OpenFootball 2021-22..2023-24 → 1,140 matches imported.
- Stage 9 MLE walk-forward completed; report in `results/stage9_mle/REPORT.md`.
- Stage 3 + Stage 8 comparison in `results/stage3_stage8_eval.json`.
- **88 unit tests passed.**
- Champion retained: `alea-dc-v2.4.1`.
- Full write-up: `ALEA_3.0_FINAL_TECHNICAL_REPORT.md`.

---

## Promotion decisions

| Candidate | Holdout LL | Decision |
|-----------|-----------:|----------|
| DC v2.4.1 | **0.9427** | **champion** |
| Elo alone | 0.9591 | reject |
| DC+Elo equal | 0.9457 | reject |
| DC+temperature | 0.9480 | reject |
