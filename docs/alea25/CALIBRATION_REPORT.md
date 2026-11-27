# ALEA 2.5 Calibration Report

**Date:** 2026-11-27  
**Branch:** `dev/alea-2.5-improvements`  
**Champion (unchanged):** `alea-dc-v2.4.1`  
**SHA-256:** `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`

## Protocol

- Data: OpenFootball Premier League 2019-20 … 2025-26 (2 660 matches).
- Model: frozen champion ξ=0.0018, reg=1.0.
- Walk-forward: min train 380, step 35 days, 18 folds → **770** OOS predictions.
- Training cutoff for every prediction is strictly before the match date.
- Calibration fit window: earlier 60% of OOS (462 matches, 2020-09-12 … 2021-10-23).
- Calibration eval window: later 40% of OOS (308 matches, 2021-10-23 … 2022-08-07).
- No same-day leakage; Stage-8 chronology guards enforced.

## Results (held-out eval window, n=308)

| Method | Log loss | Brier | RPS | Accuracy | ECE |
|--------|----------|-------|-----|----------|-----|
| Uncalibrated champion | **0.9583** | **0.5669** | **0.1988** | 0.542 | **0.0459** |
| Temperature (T≈1.167) | 0.9618 | 0.5690 | 0.1995 | 0.542 | 0.0535 |
| Isotonic (per-class) | 1.0732 | 0.5771 | 0.2038 | 0.519 | 0.0564 |

### Temperature scaling detail

- Fitted T = 1.1669 on the fit window (small in-sample LL improvement ≈ 0.0021).
- On the eval window the calibrated model is **slightly worse**.
- Paired ISO-week block bootstrap (1000 resamples): mean ΔLL = +0.0034, 95% CI [−0.0047, +0.0103] → **inconclusive** (does not establish improvement).

### Isotonic

- Per-class isotonic fitted on 462 samples, applied to eval.
- Severe degradation on eval (LL 1.073 vs 0.958) — classic over-fit of a flexible calibrator.
- Should **not** be applied.

### Period stability (uncalibrated vs temperature)

| Period | n | Uncal LL | Uncal ECE | Temp LL | Temp ECE |
|--------|---|----------|-----------|---------|----------|
| 2020-09-12 … 2021-01-27 | 192 | 1.046 | 0.073 | 1.039 | 0.068 |
| 2021-01-27 … 2021-08-14 | 192 | 1.005 | 0.070 | 1.005 | 0.076 |
| 2021-08-14 … 2022-01-15 | 192 | 0.958 | 0.051 | 0.962 | 0.054 |
| 2022-01-15 … 2022-08-07 | 194 | 0.959 | 0.066 | 0.962 | 0.055 |

Temperature helps ECE slightly in some early periods and hurts LL in later ones. No stable win.

## Decision

- **Do not apply temperature scaling in production** — eval metrics and bootstrap CI do not support it.
- **Do not apply isotonic calibration** — clear over-fit.
- **Champion remains the production probability source** without post-hoc recalibration.
- No promotion exercise; no ledger or registry changes.

## Reproducibility

```bash
python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26
# export CSV via stages.stage1 data store (see run_calibration.py loader)
python -m experiments.alea25.run_calibration --max-folds 20 --step-days 35 \
  --out results/alea25/calibration_report.json
```

Machine-readable report: `results/alea25/calibration_report.json` (gitignored under `results/`).

## Limitations

1. Eval window ends mid-2022; later seasons not in this particular calibration split.
2. Single global temperature only.
3. Isotonic needs far more data or stronger regularisation to generalise.
4. Prospective sample still below the 300-fixture promotion threshold.
