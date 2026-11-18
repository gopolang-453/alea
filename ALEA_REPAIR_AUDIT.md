# ALEA repair audit and acceptance plan

**Audit date:** 18 November 2026  
**Target branch:** `repair/alea-3.0-end-to-end`  
**Release status:** NOT READY. Do not merge to `main`, publish a model version, or enable staking.

This document records defects and missing evidence found by inspecting the repository, its stage files, the frozen predictor, the development candidate, and the prior full audit. It is an implementation checklist, not a claim that the work is complete.

## Root cause

ALEA has a functioning Dixon–Coles baseline and several tested feature calculators, but it is not yet one evidence-backed, end-to-end forecasting system. Stages 3–8 are not proven to improve the production predictor; Stage 9 has not produced a valid untouched prospective evaluation; Stages 10–12 are contracts/scaffolding rather than a deployed pipeline. Stage 13 correctly remains blocked.

## Stage-by-stage defects and fixes

| Stage | Actual problem | Required fix | Acceptance test |
|---|---|---|---|
| 1 — Data | SQLite importer and OpenFootball fetcher exist, but the current source is a moving upstream dataset and date-only result availability is conservative. No versioned end-to-end production snapshot/refresh process has been demonstrated. | Keep raw source files and SHA-256 manifests; validate season identity, fixture uniqueness, played-result completeness, team aliases, and idempotent imports. Persist the exact source hash used by every run. | Re-import same files: zero new rows. Alter a duplicate score: hard failure. Snapshot before next-day availability: result absent; after availability: present. |
| 2 — Dixon–Coles | Standalone Stage 2 maths and production predictor duplicate core formulas, so they can drift. | Add parity tests comparing scoreline cells, 1X2, BTTS, totals and tail mass between the independent module and production implementation over ordinary and edge-case parameters. | All probabilities finite and in [0,1]; 1X2 sums to 1; score grid plus tail sums to 1; parity within stated numeric tolerance. |
| 3 — Team strength | Elo/form/H2H calculators exist but are not inputs to the production goal-rate model. | Build a date-safe feature adapter and a separately versioned candidate model. Fit any Elo coefficient on development folds only; compare against identical Dixon–Coles folds. | Every fixture feature uses only results available before its date. Keep Elo only if paired out-of-sample log loss and Brier/RPS improve without a material calibration regression. |
| 4 — xG | Calculators exist, but OpenFootball results do not provide xG and no timestamped historical xG feed is wired in. | Add a real xG source with source ID, fixture key, retrieval/availability timestamp and coverage report. Until then, xG must remain disabled, not imputed. | No xG value is visible before its recorded availability; missing coverage returns unavailable; xG candidate evaluated on exactly the same fixtures as baseline. |
| 5 — Player intelligence | Injury/lineup lookups exist; player impact is explicitly an untrained placeholder and returns no numeric impact. | Add timestamped historical injury/lineup and player-strength data, then estimate impact only from training-period data. Do not turn positional guesses into goal adjustments. | Historical lineup/injury snapshot reproduces what was known at forecast time; absent or uncertain player data has no numeric effect. |
| 6 — Context | Weather/referee/manager/travel/derby are feature contracts, not a sourced model. | Connect trustworthy timestamped sources individually; define coverage and missingness. Test each feature alone before combining. | No post-match context leaks into a pre-match forecast; feature ablation beats baseline on common out-of-sample fixtures before acceptance. |
| 7 — ML/ensemble | Current module is an ensemble contract; no trained candidate or evidence-backed weights are present. | Only after data/features are available, train a regularised candidate (simple multinomial/logistic or gradient-boosted model) on chronological folds. Learn ensemble weights on validation data only. | Compare to DC and bookmaker benchmark on identical fixtures. Candidate must beat DC with paired uncertainty intervals and not materially worsen Brier/RPS/calibration. |
| 8 — Calibration | Temperature scaling is implemented as a helper, but is not integrated into forecast generation. Prior audit found temperature scaling did not help. | Fit calibration only on earlier out-of-sample predictions; store calibrator version and training window. Apply only if validation gain survives a later untouched test. | Calibration cannot see same-day/future outcomes. Reliability and log loss improve on later unseen data; otherwise use T=1/no calibrator. |
| 9 — Backtesting | A walk-forward runner and importer exist, but no completed real-data run is recorded for this branch. Runner currently imports frozen v2.4.1 only. Existing historical samples have already informed model changes, so they are diagnostic, not a clean blind test. | Run reproducible multi-season development evaluation, compare frozen baseline and repaired candidate on identical dates, and begin an immutable prospective forecast ledger for the remainder of 2026/27. Never call already-inspected seasons untouched. | Each forecast is stored before kickoff with model/code version, data snapshot hash and cutoff. No same-day overlap. Score only after results become available. Publish log loss, Brier, RPS, accuracy, calibration, coverage, baseline and bookmaker comparisons with paired confidence intervals. |
| 10 — Automation | Registry/promotion logic exists in isolation; no scheduled pipeline feeds it validated evaluation evidence. | Connect scheduled ingest → snapshot → forecast → result reconciliation → metrics. Promote only with sufficient sample and uncertainty-aware gates. | Failed/stale ingest blocks forecasts and promotion; candidate cannot promote without holdout evidence; rollback restores prior champion and verifies hash. |
| 11 — Prediction service | Prediction/history contract exists but is not a deployed, end-to-end service backed by the live data pipeline. | Connect fixture discovery, cutoff-safe fitting, prediction response and append-only history. Return explicit unavailable states for missing xG/player/context fields. | A forecast can be retrieved later byte-for-byte with fixture, probabilities, model version, cutoff and snapshot hash; duplicate writes are idempotent. |
| 12 — Reliability | Backup/restore and secret-scan contracts exist, but no operational monitoring/backup schedule has been demonstrated. | Add scheduled backups, restore drills, freshness alerts, model/data integrity checks and CI security scanning. | Corrupt backup is rejected; valid backup restores; stale data blocks prediction; secret scan fails on a test secret and passes clean repository. |
| 13 — Acceptance | Correctly marked incomplete. | Close all preceding gates, produce the prospective report, then issue a release candidate. | All automated tests green, no unresolved critical defects, prospective evaluation report published, deployment/restore drill passes. |

## Confirmed model-quality evidence that must constrain the repair

The repository's 12 November 2026 full audit reports, on 1,140 previously examined matches:

- Frozen v2.4.1: log loss 0.9964, Brier 0.5876, RPS 0.2021, accuracy 0.518.
- Development candidate: log loss 0.9868, Brier 0.5881, RPS 0.2022, accuracy 0.519.
- Bet365 closing market (Shin de-vig): log loss 0.9595, Brier 0.5698, RPS 0.1937, accuracy 0.550.
- Development minus v2.4.1 log-loss difference: -0.0096; 95% interval -0.033 to +0.003, which includes zero.
- Development minus market log-loss difference: +0.027; 95% interval +0.015 to +0.038.
- The value-engine strategy lost 11.9% per unit over 1,046 bets; its 95% interval was -21.2% to -2.1%.

Therefore:
1. The development candidate is a numerical-safety repair, not evidence of a generally superior predictor.
2. The market is currently the stronger benchmark.
3. The existing odds-timing assumptions are not verified timestamps.
4. Staking must remain disabled.
5. Do not tune on the 2023/24–2025/26 matches already examined. Begin prospective evaluation from a frozen code/data cutoff and score future fixtures only.

## Immediate execution order

1. Finish and pass the offline CI suite on this repair branch.
2. Fix every concrete failing test before adding new model logic.
3. Run the Stage 9 importer and walk-forward script against real historical data as a diagnostic reproduction; publish source hashes and all metrics.
4. Compare frozen v2.4.1 with the development candidate on identical chronological folds. Keep both outputs; do not silently replace the baseline.
5. Implement the prospective forecast ledger for future 2026/27 fixtures. Store predictions before kickoff and score after results become available.
6. Integrate Stage 3 Elo first as the only currently computable historical feature. Evaluate it as an ablation; reject it if it does not improve.
7. Do not activate Stages 4–6 until actual timestamped data feeds exist. Do not train Stage 7 until enough valid feature rows exist. Do not activate Stage 8 unless calibration improves later unseen results.
8. Connect Stages 10–12 only after the forecast pipeline and evidence gates work.
9. Re-run all automated tests, security scan, data-integrity tests and restore drill. Only then prepare a release PR.

## Definition of done

ALEA is done only when a user can request a real upcoming fixture prediction; the response gives 1X2 probabilities, scoreline/goal markets, data freshness and uncertainty; the system can reproduce exactly which data/model produced it; predictions are stored before kickoff; later results are scored automatically; and an independent prospective report shows how it performs against DC baselines and the market. No claim of a betting edge is permitted without separate, statistically credible evidence.
