# ALEA 3.0 — Final Technical Report

**Branch:** `repair/alea-3.0-end-to-end`  
**Report date:** 20 November 2026  
**Frozen champion:** `alea_predictor_v2_4_1.py` (`alea-dc-v2.4.1`)  
**Holdout:** Premier League 2023-24 (380 matches, OpenFootball CC0)

---

## 1. Original project condition

ALEA shipped a working Dixon–Coles MLE predictor (v2.4.1) with strong mathematical checks, but the repair branch had incomplete stage scaffolding, team-name mismatches that blocked OpenFootball → MLE evaluation, and no committed real-data walk-forward artifact on the repair tip.

---

## 2. Defects identified and corrected

| Defect | Fix | Commit |
|--------|-----|--------|
| OpenFootball names retained `FC`/`AFC` suffixes; production `clean_matches` rejected them | Strip FC/AFC in `canonical_team`; runner calls production `clean_matches` before fit | `ec77871`, `7272a14` |
| Stage 9 runner could not complete a real walk-forward | Name cleaning + successful 3-season run | `7272a14` + local evidence |
| Stage 3 probability mapping never evaluated vs champion | Elo alone and DC+Elo scored on identical holdout | `75dbd75` |
| Stage 8 calibration never proven | Temperature fit on development; applied to holdout; rejected | `cd37c7a` |
| Progress docs claimed unfinished work | STATUS files and this report updated from execution evidence | multiple |

---

## 3. Files modified (repair branch)

- `stages/stage1/persistent_store.py` — FC/AFC strip, expanded aliases
- `scripts/run_stage9_mle_backtest.py` — production `clean_matches` before every fit
- `results/stage9_mle/REPORT.md` — real holdout evidence
- `results/stage3_stage8_eval.json` — Elo + temperature comparison
- Stage STATUS files (1, 3, 8, 9, 13)
- `STAGE_PROGRESS_REPORT.md`
- This report

**Not modified:** `alea_predictor_v2_4_1.py` (frozen reference).

---

## 4. Tests executed

| Suite | Result |
|-------|--------|
| Stage 1, 2, 7, 8, 9, 10 unit tests | **71 passed** |
| Stage 3, 4–6 safety, 11, 12 unit tests | **17 passed** |
| **Total executed this session** | **88 passed** |

No test was marked passed without execution.

---

## 5. Backtesting methodology

- **Source:** OpenFootball CC0 Premier League JSON (2021-22, 2022-23, 2023-24) → Stage 1 `PersistentDataStore`
- **Fingerprint:** `46623bc9460eaed6a7afa78141cfcfd637272e1dccb0b7b716a1b34d848c0f0e`
- **Model:** frozen `alea-dc-v2.4.1`, xi=0.0018, reg=1.0 **fixed** (not tuned on holdout)
- **Protocol:** chronological expanding window; calendar dates kept together; min 200 training matches; 60-day test blocks
- **Holdout:** full 2023-24 season (380 matches), never used for parameter choice
- **Baselines:** training-rate (empirical 1X2 frequencies) and uniform 1/3

---

## 6. Champion performance (Stage 9)

| Period | n | Log loss | Brier | RPS | Accuracy |
|--------|--:|---------:|------:|----:|---------:|
| Development walk-forward | 559 | 0.991 | 0.590 | 0.209 | 0.553 |
| **Holdout 2023-24** | **380** | **0.943** | **0.557** | **0.194** | **0.579** |
| Holdout rate baseline | 380 | 1.054 | 0.637 | 0.234 | 0.461 |
| Holdout uniform | 380 | 1.099 | 0.667 | 0.242 | 0.461 |

Champion beats both baselines on every reported metric.

Holdout calibration snapshot: predicted H/D/A frequencies (45.6 / 21.4 / 33.0%) match actual base rates (46.1 / 21.6 / 32.4%). Draws remain under-confident when they occur (mean p_draw | actual=D ≈ 0.22).

---

## 7. Candidate comparisons (same 380 holdout fixtures)

| Candidate | Log loss | vs champion | Decision |
|-----------|----------:|-------------|----------|
| DC v2.4.1 | **0.9427** | — | **champion** |
| Elo alone | 0.9591 | worse | reject |
| DC + Elo equal | 0.9457 | worse | reject |
| DC + temperature (T=1.20 from development) | 0.9480 | worse | reject |

No candidate cleared the acceptance gate.

---

## 8. Calibration results

- Temperature fitted on 559 development predictions only: T = 1.200, development LL improvement +0.0037.
- Applied once to holdout: LL worsened from 0.943 to 0.948.
- **Calibration not enabled.**

---

## 9. Stage-by-stage completion status

| Stage | Status | Evidence |
|-------|--------|----------|
| 1 Data store | **PASS** | Import, fingerprint, FC/AFC fix, unit tests |
| 2 Dixon–Coles maths | **PASS** | Exact markets, parity test, frozen model |
| 3 Elo / form | **PARTIAL** | Features OK; probability candidates rejected on holdout |
| 4 xG | **BLOCKED** | No licensed timestamped historical xG source; calculators fail closed |
| 5 Player / injury | **BLOCKED** | No source; stubs refuse invented impact weights |
| 6 Context | **BLOCKED** | No source; calculators fail closed |
| 7 Ensemble | **PARTIAL** | Contracts + metrics tested; no trained booster (no feature matrix with evidence) |
| 8 Calibration | **PARTIAL** | Implemented; rejected on holdout |
| 9 Walk-forward | **PASS (core)** | Real OpenFootball MLE holdout evidence committed |
| 10 Registry | **PARTIAL** | Evidence-gated promote/rollback unit-tested; not deployed |
| 11 Prediction service | **PARTIAL** | Traceable prediction builder + immutability contracts; not deployed |
| 12 Reliability | **PARTIAL** | Checksum, backup/restore, secret-scan utilities unit-tested |
| 13 Integration / release | **NOT COMPLETE** | See recommendation |

---

## 10. Remaining limitations

1. No licensed closing-odds series with timestamps → no market edge measurement.
2. No historical xG / injury / weather feeds → Stages 4–6 correctly disabled.
3. No live scheduler or production deployment.
4. Draw under-confidence is real; fixing it needs a candidate that beats 0.943 LL on this holdout without holdout tuning.
5. RPS implementation details differ slightly between ad-hoc scripts and `dc.rps_score`; official ranking uses Stage 9 report numbers.

---

## 11. Final release recommendation

**Do not tag v3.0.0 or merge to `main` as a “completed 13-stage system.”**

**Do** treat the following as the current scientific baseline:

- Production model remains **`alea-dc-v2.4.1`**.
- Stage 1 store + OpenFootball path + Stage 9 protocol are operational and evidenced.
- Elo, equal ensembles, and temperature scaling are **not** promoted.
- Stages 4–6 stay fail-closed until real data arrives.

A future candidate may replace the champion only if it is evaluated on **identical fixtures and cutoffs**, is not tuned on the holdout, improves log loss (primary) without material damage to Brier/RPS/calibration, and is registered through Stage 10 with the evidence metrics required by `ModelRegistry.promote`.

---

## 12. Reproduce

```bash
python scripts/fetch_openfootball.py --seasons 2021-22 2022-23 2023-24
python scripts/run_stage9_mle_backtest.py --holdout-season 2023-24 --min-train-matches 200 --step-days 60
python -m pytest tests/ -q
```

Primary artifacts:
- `results/stage9_mle/REPORT.md`
- `results/stage3_stage8_eval.json`
- This file
