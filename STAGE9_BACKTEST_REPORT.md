> **Superseded (24 Nov 2026):** see [ALEA_3.0_STATUS_REPORT_2026-11-24.md](ALEA_3.0_STATUS_REPORT_2026-11-24.md) for current, re-measured status. Kept for history only.

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


---

## Repository reproducibility update — 18 November 2026

A later repository audit found that the 1,900-match historical run described above is **not reproducible from the committed checkout**: the referenced five-season CSV files and the persistent-store module originally imported by the Stage 9.1 test were absent. Treat the metrics above as reported experiment results, not independently verified release evidence.

The repository now has a SQLite-backed Stage 1 store and CSV importer, idempotent duplicate handling, conservative date-only result availability, a small synthetic CSV fixture, and regression tests. GitHub Actions run [44297685638](https://github.com/gopolang-453/alea/actions/runs/44297685638) passed 8 Stage 1 / Stage 9.1 tests on commit `01b8a5d8890ff0cb66b3ec1998b898d105a25559`.

That smoke test does **not** reproduce the 1,900-match dataset or the 1,600-prediction walk-forward. The production Dixon–Coles MLE walk-forward and Stage 9.5 combined-model evaluation remain open. Stage 13 remains NOT COMPLETE.
