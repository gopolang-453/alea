# ALEA 3.0 — End-to-end repair plan

**Working branch:** `repair/alea-3.0-integrated`  
**Baseline commit:** `18e2e94c0fdfe1a43376e36e31c6f7c1db85d73d` (latest main when integrated branch was created)  
**Status:** Audit and repair plan only. No acceptance stage is passed by this document.

## 1. Repair policy

1. Preserve `alea_predictor_v2_4_1.py` and `frozen/` as immutable reference implementations.
2. Keep all repairs on this branch until the full test suite and acceptance checks pass. Do not overwrite `main` or issue a release prematurely.
3. A stage is PASS only when its code, automated tests, reproducible evidence and documentation agree.
4. Never turn missing data into zero, a guessed impact, or a default confidence value. Missing/late data must be explicitly represented and excluded or handled by a documented model rule.
5. Never use future results, post-match statistics, closing odds unavailable at prediction time, or data with unknown availability timestamps as pre-match features.
6. Keep betting/staking disabled. Predictive performance is not evidence of a profitable betting edge.
7. Record data source, licence, retrieval time, file hash, schema version, model version, training cutoff and prediction timestamp for every experiment.

## 2. Repository audit — confirmed blockers

The current default-branch tree does not match its status reports:

- `stages/stage9/tests/test_stage9_1_real_data.py` imports `stages/alea_stage1/persistent_store.py`, which is absent. The actual Stage 1 module is `stages/stage1/data_store.py`.
- That test expects `stages/data/epl/E0_1920.csv` through `E0_2324.csv`; none of those files or that directory is present in the repository tree.
- The actual `DataStore` in `stages/stage1/data_store.py` is in-memory only. It has no SQLite persistence, and `add()` appends without duplicate/idempotency protection.
- The report names `results_stage9_baseline.csv`, but that file is absent from the repository tree.
- The existing Stage 1 ingestion assigns availability at midnight UTC plus three hours, not from a verified kickoff/completion timestamp. That can make a result appear available before an evening match has finished.
- Stage 2's matrix aggregation functions normalise the finite score grid. This discards the meaning of the reported tail and can bias 1X2/BTTS/totals when the grid is truncated.
- Stage 5's `player_impact_stub()` contains hand-authored positional weights. It is a placeholder, not a measured player impact model, and must not silently affect production probabilities.
- Stage 7 is probability-metric/ensemble scaffolding; it does not train an ML model.
- The baseline tree has no `stages/stage3`, `stages/stage8`, `stages/stage10`, `stages/stage11` or `stages/stage12` implementation directories. This branch adds first-pass implementations for those stages, but they remain subject to test and integration gates.
- Stage 9 contains a test file but no committed backtest harness module or real-data result artifact.
- The repository has no connected production pipeline joining ingestion, features, fitting, walk-forward evaluation, prediction persistence, and scheduled refresh.

These findings mean previous Stage 9 PASS claims are not independently reproducible from the current committed tree. Re-run them after the missing implementation and artifacts are restored.

## 3. Data-source decision

Do not build automated model training on Football-Data.co.uk without permission. Its data page says the free data is for private individuals and excludes commercial or AI-training products using automated bots/scrapers:
https://www.football-data.co.uk/data

Use OpenFootball's Premier League historical JSON as the initial results-only source, subject to rechecking the repository licence and source provenance at implementation time:
https://github.com/openfootball/football.json
Its README states the data is public domain / CC0. It is a volunteer-maintained historical fixture/results dataset, not a guaranteed live-score service:
https://github.com/openfootball/help

Consequences:
- OpenFootball can support a reproducible results-only historical baseline.
- It does not supply historical xG, injuries, confirmed lineups or reliable live updates.
- Those features remain disabled until a separately licensed, timestamped source is identified.
- Do not copy Football-Data CSVs into this repository or train on them unless the rights holder explicitly permits that use.

## 4. Implementation sequence and acceptance gates

### Phase A — Make the repository truthful and runnable

**A1. Repair the Stage 9 test layout**
- Replace the nonexistent import path with the actual Stage 1 package path.
- Remove hard-coded expectations for files that are not committed.
- Split tests into offline unit tests using small synthetic fixtures and an explicitly opt-in integration test that downloads a licensed public dataset.
- The ordinary test command must not require internet access.

**A2. Implement a real persistent Stage 1 store**
- Build on the SQLite persistence already in `stages/stage1/data_store.py`; preserve its append-only snapshot API.
- Preserve the season in every imported result record and output frame.
- Make imports idempotent: identical re-imports add zero records; conflicting records from the same source revision fail closed.
- Preserve source URL, retrieval time, raw-file SHA-256 manifest and source identifier.
- Store both event date and availability time.
- If kickoff/completion time is unavailable, require at least 24 hours of delay (36 hours by default); never expose a date-only result on match day.
- Validate required fields, date parsing, team names, integer nonnegative goals, duplicates, conflicting duplicates and impossible team-vs-self fixtures.
- Add tests for persistence after reopen, idempotency, conflicting imports, timezone-aware cutoffs, snapshots and unavailable/future information.

**A3. Restore reproducible historical data**
- Add a downloader/parser for OpenFootball season JSON, with explicit season list and source URLs.
- Save raw files outside Git by default; write checksums and provenance metadata.
- Normalise into the Stage 1 schema.
- Verify season coverage, match counts against source files, date range, duplicate fixture keys and result completeness. Do not hard-code 380 matches as a universal rule.
- Add a small checked-in synthetic fixture for offline tests, not a full historical data dump unless licensing and repository size are reviewed.

**A4. Make one canonical test command**
- Add a top-level test runner (or pytest configuration) that runs all unit tests and exits non-zero on any failure.
- Ensure imports work from repository root.
- CI must install pinned dependencies and run the same command on a clean checkout.
- Reports must state exact commit SHA, Python/dependency versions, test command and test count.

**PASS A:** a fresh clone can install dependencies and pass all offline tests; the public dataset can be fetched and imported by a separate integration command; re-import is idempotent; the data provenance is reproducible.

### Phase B — Correct and verify the probability engine

**B1. Make Stage 2 mathematically consistent**
- Validate finite positive expected-goal rates, finite rho, supported rho range, and score-grid size.
- Keep score-grid tail mass explicit.
- Implement 1X2 probabilities using the full distribution (or a proven converged calculation), not a renormalised truncated grid.
- Implement BTTS and totals with exact formulas or an explicit tail/error bound.
- Test that results converge across grid sizes, probabilities are finite and in [0,1], and 1X2 sums to 1 within numerical tolerance.
- Compare the independent Stage 2 implementation against the production predictor on fixed parameter fixtures.

**B2. Validate the production Dixon–Coles implementation**
- Retain the current v2.4.1 frozen reference.
- Use the development candidate only as a candidate; do not promote it based on the same matches used to discover the defect.
- Test optimiser convergence, parameter bounds, rho validity for unseen team pairings, shrinkage, zero-goal teams, new/promoted teams, extreme scores, save/load and deterministic prediction.
- Reject failed/non-converged fits rather than returning probabilities.
- Add numerical guards for NaN/inf and impossible probability vectors.

**PASS B:** independent formulas and production outputs agree within documented tolerances; full probability distributions are valid; no known pathological fit produces collapsed probabilities.

### Phase C — Build one leakage-safe feature and prediction pipeline

**C1. Establish a single feature interface**
- Every feature builder receives a fixture and an explicit timezone-aware `as_of` timestamp.
- Every input record has an `available_at` timestamp.
- A feature must never inspect a result or statistic that was not available at `as_of`.
- Missing data returns an explicit missing state, not a guessed value.

**C2. Team strength and form**
- Implement Elo and recent-form features from prior results only.
- Fix update ordering for matches on the same date: do not let one match's result update another match's prediction from the same kickoff/date unless verified kickoff ordering permits it.
- Convert ratings into 1X2 probabilities through a fitted, training-only mapping; remove the fixed 0.25 draw shortcut.
- Compare Elo-only, form-only and combined variants against the production Dixon–Coles baseline on identical folds.

**C3. xG, player and context features**
- Do not enable xG, injuries, suspensions, lineups, referee, weather, manager, travel or derby features until there is a source with suitable rights and trustworthy historical availability timestamps.
- Replace the Stage 5 hand-authored impact stub with an explicitly non-predictive metadata-only output, or keep it out of the probability model.
- Test each real feature independently before combinations. Reject or mark experimental any feature that fails to improve out-of-sample probability quality.

**C4. Ensemble and ML**
- Validate model names, complete fixture alignment, finite nonnegative weights and probability vectors.
- Reject duplicate fixture predictions and invalid outcomes.
- Train no LightGBM/XGBoost merely to satisfy a roadmap checkbox. Train only if enough licensed, leakage-safe features and samples exist and the candidate beats simpler baselines on a predeclared holdout.
- Learn ensemble weights on validation data only; never on the final test set.

**PASS C:** the production predictor can consume one canonical fixture and a snapshot, build only eligible features, and return reproducible, traceable probabilities. Every enabled feature has out-of-sample evidence.

### Phase D — Real walk-forward evaluation (Stage 9)

**D1. Freeze the protocol before scoring**
- Use chronological expanding-window evaluation with all matches from a calendar date kept together unless reliable kickoff timestamps justify finer ordering.
- Set minimum training history and test block size before inspecting outcomes.
- Tune hyperparameters only inside each training window using an inner chronological validation split.
- Keep a final untouched holdout period. Do not tune or choose features on it.
- Save each prediction before joining the final outcome; record model version, training cutoff, data snapshot hash and feature availability audit.

**D2. Compare identical fixtures**
- Production Dixon–Coles MLE baseline.
- Independent Poisson baseline.
- Elo and form individually, then combined.
- Market probabilities only when odds data is licensed and the odds timestamp is demonstrably available before kickoff.
- All models must be evaluated on exactly the same fixtures for each paired comparison.

**D3. Report metrics**
- Multiclass log loss, multiclass Brier (state the convention), ranked probability score, accuracy and class frequencies.
- Calibration/reliability by class and probability bins, with sample counts and uncertainty intervals.
- Season-by-season and overall results.
- Paired bootstrap confidence intervals for metric differences.
- Include benchmark scores and sample sizes; no accuracy-only claims.
- Do not interpret a Brier improvement as calibration improvement by itself; Brier mixes calibration, resolution and outcome uncertainty.

**D4. Acceptance rule**
- A candidate is promoted only if it beats the baseline on predeclared primary metrics on the untouched holdout, does not materially damage secondary metrics/calibration, and the paired uncertainty supports a real improvement.
- If results are inconclusive, keep the simpler baseline and label the candidate experimental.
- Re-run the same experiment from a clean checkout and verify identical predictions/metrics.

**PASS D:** a fully reproducible production-MLE walk-forward and final combined-model holdout report exist. No feature is called beneficial on the basis of training or tuning results.

### Phase E — Automation, interface and operational reliability (Stages 10–12)

**E1. Data updater**
- Use a documented source adapter with timeouts, retries, backoff, response validation and source health status.
- Separate fixtures from completed results.
- Make every update idempotent and auditable.
- Do not describe a volunteer dataset as live or guaranteed.
- If no licensed dependable live source exists, keep scheduled ingestion disabled and document the manual update procedure.

**E2. Model lifecycle**
- Fit a candidate in an isolated run; validate on chronological data; promote only when the acceptance rule passes.
- Store immutable model artifacts and metadata.
- Test rollback to the previous champion, interrupted training, corrupted artifacts and incompatible model versions.

**E3. Prediction interface**
- Provide one command/API to predict a fixture.
- Return home/draw/away probabilities, expected goals, scoreline distribution and optional totals/BTTS only where supported.
- Display model version, data cutoff, data freshness, missing features and uncertainty caveats.
- Persist predictions immutably so historical outputs can be reproduced.

**E4. Security and reliability**
- Keep credentials out of source control; scan the full repository and Git history where possible.
- Add structured logs, health checks, data freshness alerts, error handling and backup/restore.
- Test empty/malformed data, upstream outage, DB failure, model corruption and recovery.
- Document a clean installation and recovery procedure.

**PASS E:** a fresh deployment can ingest supported data, produce a traceable prediction, survive simulated failures and restore the previous known-good model.

### Phase F — Stage 13 final acceptance and release

Stage 13 remains OPEN until all of the following are true:

- A1–A4 and B1–B2 pass.
- The production predictor is connected to the canonical data/feature pipeline.
- D1–D4 pass on licensed data with an untouched holdout.
- Every included feature is evidence-backed; unsupported features are disabled and clearly labelled.
- E1–E4 pass, or unsupported live automation is explicitly excluded from the release scope.
- Documentation, dependency lock, tests, data provenance and model artifacts are complete.
- A release candidate is tested from a clean checkout.
- Only then create a tagged release. Never mark Stage 13 complete merely because all unit tests pass.

## 5. First implementation milestone

Do not start by training XGBoost or adding more features. The first coding milestone is **Phase A**: build on the existing Stage 1 SQLite store, repair the broken Stage 9 test/import structure, preserve season metadata, add an offline parser fixture, and provide a licensed OpenFootball importer. Only after Phase A passes should the historical backtest be trusted.
