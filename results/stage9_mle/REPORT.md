# Stage 9 — Production MLE walk-forward evidence

**Run date:** 2026-11-20  
**Branch tip at run:** includes Stage 1 FC/AFC fix + clean_matches in runner  
**Data:** OpenFootball CC0 Premier League 2021-22, 2022-23, 2023-24 (1,140 completed matches)  
**Database fingerprint:** `46623bc9460eaed6a7afa78141cfcfd637272e1dccb0b7b716a1b34d848c0f0e`  
**Model:** frozen `alea_predictor_v2_4_1.py` (`alea-dc-v2.4.1`)  
**Protocol:** chronological expanding window; dates kept together; xi=0.0018, reg=1.0 fixed; **not tuned on holdout**

## Results

| Period | n | Log loss | Brier | RPS | Accuracy |
|--------|--:|---------:|------:|----:|---------:|
| Development walk-forward | 559 | 0.991 | 0.590 | 0.209 | 0.553 |
| **Final holdout 2023-24** | **380** | **0.943** | **0.557** | **0.194** | **0.579** |
| Holdout training-rate baseline | 380 | 1.054 | 0.637 | 0.234 | 0.461 |
| Holdout uniform 1/3 | 380 | 1.099 | 0.667 | 0.242 | 0.461 |

## Holdout calibration snapshot

- Actual outcome mix: H 46.1% / D 21.6% / A 32.4%
- Mean predicted: H 45.6% / D 21.4% / A 33.0% (matches the base rates)
- When actual = H, mean p_home = 0.54
- When actual = D, mean p_draw = 0.22 (draws still under-confident when they happen)
- When actual = A, mean p_away = 0.44
- 16 / 380 predictions used league-average prior for at least one team (promoted/new)

## What this proves

1. The production Dixon–Coles MLE is leakage-safe under this protocol and beats naive baselines on an untouched season.
2. OpenFootball results + Stage 1 store + runner path is operational end-to-end.
3. Draw probabilities remain the weak spot (classic DC behaviour).

## What this does **not** prove

- Edge vs bookmaker closing prices (no licensed odds with timestamps in this run).
- That Elo/form/xG improve on this baseline (Stage 3 evaluation still open).
- That temperature calibration helps (Stage 8 not fitted on this artifact yet).
- Anything about betting value (staking remains off).

## Reproduce

```bash
python scripts/fetch_openfootball.py --seasons 2021-22 2022-23 2023-24
python scripts/run_stage9_mle_backtest.py --holdout-season 2023-24 --min-train-matches 200 --step-days 60
```
