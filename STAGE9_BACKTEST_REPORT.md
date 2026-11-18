# Stage 9 — Historical backtesting report
**Date:** 18 November 2026  
**Data:** 5 Premier League seasons (2019/20–2023/24), 1,900 matches from football-data.co.uk  
**Walk-forward:** expanding window, min_train=300, step=50 → 1,600 out-of-sample predictions

## 9.1 — Data import
**PASS** (prior turn). 1,900 records imported, second import added 0 duplicates, snapshot retrieves all rows.

## 9.2 — Dixon-Coles style walk-forward
**PASS (reproducible)**  
- Training uses only matches strictly before each test block.  
- Same data + settings → identical probabilities on a second run.  
- Probabilities sum to 1.

## 9.3 — Baseline metrics (attack/defence rates + Stage 2 score matrix)

| Metric | Value |
|--------|-------|
| n | 1,600 |
| Log loss | 1.057 |
| Brier | 0.635 |
| 1X2 accuracy | 0.468 |

Saved: `results_stage9_baseline.csv`

## 9.4 — Individual feature check (Elo)
Simple Elo (Stage 3) with a fixed 0.25 draw probability, same 1,600 matches:

| Metric | Elo | Baseline |
|--------|-----|----------|
| Log loss | 0.984 | 1.057 |
| Brier | 0.585 | 0.635 |
| Accuracy | 0.536 | 0.468 |

Elo improved log loss and Brier on this sample.  
**Caveat:** the Elo 1X2 conversion is crude (fixed draw). This is directional evidence, not a final model decision. xG, injuries, and contextual features still lack real historical sources, so they were not scored.

## 9.5 — Combined model
Not run as a full combined system. Only Elo showed a clear improvement in this quick check. A proper combined evaluation requires the same leakage-safe protocol on all retained features and a held-out period. Left for a follow-up once more feature sources exist.

## Notes
- The production `alea_predictor_v2_4_1.py` full MLE was not used here (too slow for this sitting). The walk-forward uses a fast rates model + the Stage 2 score matrix.
- Bookmaker de-vig comparison was not run (odds columns exist in the CSVs but were not scored in this pass).

**Stage 9 core (9.1–9.3) is complete and reproducible. 9.4 has initial Elo evidence. 9.5 is open.**
