# Historical data checklist and next-phase experiment plan

## Why more data is needed

`results/predictions_closing_odds.csv` and `results/predictions_closing_dev.csv` contain only the **1,140 evaluation matches** (11 Aug 2023 – 24 May 2026) with each fold's `n_train` count (e.g. 380, 381, ...) — but not the actual training-period match rows themselves. Those earlier matches are what every walk-forward fold trained on. Without them I can verify scoring (which I've done) but cannot refit either model from scratch, so I cannot test any genuinely new change (different `xi`/`reg`, Elo, calibration, etc.) — I'd just be re-describing the same stored predictions.

## Exact files needed

Source: football-data.co.uk, English Premier League ("E0").

Fetch the E0 CSV for each season that could plausibly have supplied training rows before 11 Aug 2023. The code's defaults reference seasons back to `"2425"`/`"2526"`, and `n_train` starts at 380 (roughly a full season), so at minimum:

| Season | File | Needed for |
|---|---|---|
| 2022/23 | `E0.csv` (season 2223) | Training history before the evaluation window starts |
| 2023/24 | `E0.csv` (season 2324) | Overlaps the evaluation window — needed either way |
| 2024/25 | `E0.csv` (season 2425) | Evaluation window |
| 2025/26 | `E0.csv` (season 2526) | Evaluation window, in progress |

If you have more seasons already downloaded locally (your memory notes mention a "football data" folder), more history is better — Dixon-Coles with time-decay (`xi`) can use it, and it lets me check how training-window length affects the fit (an explicit item below).

Required columns per file (check these actually exist in each season — they're not always consistent across years):
- `Date`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`, `FTR`
- `B365H`, `B365D`, `B365A` (Bet365 closing odds — matches what `results/` already uses)

## What I'll do once I have the files

1. **Data-quality pass** — same checks already run on the evaluation set: duplicates, missing/invalid odds, self-fixtures, result-vs-goals consistency, postponed/abandoned matches, column-name consistency across seasons.
2. **Refit v2.4.1 and the dev candidate from scratch** on the combined history, reproducing the exact same 1,140-match walk-forward windows, and confirm the refit predictions match what's already stored in `results/` (a direct check that the stored results weren't just hand-edited).
3. Only after that reproduction succeeds, run controlled single-variable experiments:

| # | Hypothesis | Change | Fixed everything else |
|---|---|---|---|
| 1 | Tuned `reg`/`xi` per fold already found by `tune_params` is near-optimal | Grid-search a wider `reg`/`xi` range on validation folds only | Same fixtures, same cutoffs |
| 2 | Longer training windows stabilise estimates | Vary `min_train_matches` | Same `xi`/`reg` |
| 3 | Home advantage should vary by team, not be a single global constant | Team-specific home advantage term | Everything else held |
| 4 | Elo ratings add information beyond Dixon-Coles attack/defence | Elo as an additional regressor on top of (not replacing) the existing model | Same fixtures |
| 5 | Probability calibration (e.g. isotonic/Platt) narrows the gap to the market | Fit a calibration layer on validation folds only, never the final holdout | Same fixtures |

Each experiment: one changed variable, evaluated on the same chronological splits, scored against frozen v2.4.1, the dev robustness candidate, and Shin-devigged closing odds, with log-loss/Brier/RPS/accuracy/calibration reported — and reported as a result even if it doesn't help. No experiment is promoted on a result inside a confidence interval that includes zero relative to the baseline it's being compared against, the same bar applied to the dev candidate above.

4. xG and other contextual features (`stages/stage4`–`stage6`) only get revisited if 1–5 above don't close the gap to the market — and only once there's a real, licensed, timestamped historical xG source, per the repo's existing stage status notes.

## What I need from you to start

Either:
- Upload the E0 CSVs for the seasons above, or
- Tell me where your local "football data" folder's files are if you can get them into this chat, or
- Confirm you want me to proceed without them — in which case I can only continue auditing/documenting what's here, not test new model changes.
