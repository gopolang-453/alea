# ALEA 3.0 — Comprehensive Repair Specification

**Repository:** gopolang-453/alea  
**Repair branch:** repair/alea-3.0-end-to-end  
**Purpose:** turn the current modules, scripts and partial stage reports into one reproducible, leakage-safe, evaluated prediction system.  
**Status:** specification; implementation and acceptance gates remain outstanding unless separately evidenced by commits and test logs.

---

# 0. Definition of “fixed”

ALEA is not complete merely because Python files import or unit tests pass. The system is complete only when:

1. A clean checkout installs and runs reproducibly.
2. Licensed historical data can be imported, validated, persisted and re-imported without duplication.
3. Every record has provenance and a trustworthy availability timestamp.
4. The production Dixon–Coles predictor runs chronologically without leakage and produces valid probabilities.
5. Candidate features are connected to the predictor and evaluated individually on identical out-of-sample fixtures.
6. The final candidate is compared with the baseline on a predeclared untouched holdout.
7. Predictions can be reproduced from their stored data/model versions.
8. Failures, missing data, model corruption and rollback are handled safely.
9. Reports, tests and repository status agree with the actual implementation.
10. Any unsupported feature or live service is clearly marked unavailable, not pretended to work.

No one can guarantee that the model will beat the market or make money. The engineering goal is a correct, calibrated, independently evaluated prediction system. Betting/staking stays disabled unless separately proven by a prospective, cost-aware study.

# 1. Confirmed repository issues to repair first

The current repository audit identified these mismatches:

- The Stage 9.1 test imports `stages/alea_stage1/persistent_store.py`, but the repository contains `stages/stage1/data_store.py`; the former path is absent.
- That test expects five CSVs under `stages/data/epl/`, but those files and that directory are absent from the repository tree.
- The actual Stage 1 `DataStore` is in-memory, not SQLite-backed. Its `add()` method appends records and does not enforce idempotency.
- The report references `results_stage9_baseline.csv`, but that artifact is absent from the repository tree.
- Stage 1's default availability calculation treats the match date as midnight UTC plus three hours. That is not a verified final-whistle or publication time and can make evening-match results appear available before they were known.
- Stage 2 score-grid calculations truncate the Poisson distribution. Its 1X2 and related functions renormalise the remaining grid; this can conceal tail mass and bias outputs when the grid is too small.
- Stage 5 contains hand-authored player-impact weights. These are placeholders, not empirically fitted player effects; they must not silently change production predictions.
- Stage 7 is scaffolding for metrics and ensembles, not a trained LightGBM/XGBoost implementation.
- Feature modules are not yet demonstrated as one integrated, reproducible prediction pipeline.
- Reports make claims that cannot currently be reproduced from the committed source/data/artifacts. These claims must be re-run or downgraded.

These are concrete repair targets, not a reason to delete the existing work.

# 2. Non-negotiable engineering rules

- Preserve `alea_predictor_v2_4_1.py` and `frozen/` as immutable reference code. Do not silently change the frozen benchmark.
- Make changes on `repair/alea-3.0-end-to-end`; do not push experimental repairs directly to `main`.
- Every feature must have a clear definition, input schema, availability rule, missing-data behaviour, tests and evaluation result.
- Use timezone-aware timestamps. Distinguish event time (when the match happened) from availability time (when the information became knowable).
- Never use post-match statistics as pre-match predictors for that same match.
- Never use future results, future standings, future team ratings, future lineups or future odds.
- Keep all matches on the same date in one test block unless reliable kickoff timestamps and strict event ordering are available.
- Missing data must remain missing. Do not replace missing xG/injury/lineup/weather with invented zeros or arbitrary player impacts.
- Every prediction must record model version, training cutoff, data snapshot hash, feature snapshot/cutoff, prediction timestamp and fixture identifier.
- Use a final untouched holdout only once. Do not tune thresholds, select features or calibrate on it.
- Report log loss, Brier, RPS, calibration and uncertainty, not accuracy alone.
- Do not promote a candidate on a tiny or statistically inconclusive metric difference.
- Do not enable staking or claim profitability from historical backtests.

# 3. Phase A — Repair the repository and make it runnable

## A1. Establish a reproducible project environment

1. Inspect all imports and package paths from the repository root.
2. Add explicit package initialisers where required and use stable package imports.
3. Pin compatible dependency versions in a lock file or fully pinned requirements file.
4. State the supported Python version.
5. Provide one documented setup command and one documented offline test command.
6. Make the default test suite independent of internet access.
7. Add CI that checks out a clean copy, installs pinned dependencies, runs lint/type checks if adopted, and executes the same test command.
8. Ensure all test failures return a non-zero process exit code.

**Tests**
- Clean environment install.
- Import each production module from repository root.
- Run the entire offline test suite.
- Run twice and compare outcomes.
- Verify no test relies on a developer's local untracked CSV or model file.

**PASS A1:** a clean clone installs and runs the offline suite without hidden local dependencies.

## A2. Repair the Stage 9.1 test

1. Replace the nonexistent `stages.alea_stage1.persistent_store` import with the chosen real Stage 1 package interface.
2. Do not hard-code test paths to absent five-season CSVs.
3. Split tests into:
   - unit tests using a small synthetic dataset committed to the repository;
   - opt-in integration tests which retrieve the external public dataset;
   - full historical evaluation tests which consume a locally configured data directory.
4. A missing external dataset must cause a clear skip/error with setup instructions, not a false PASS.
5. Tests must assert actual behaviour, not just that a file exists.

**Tests**
- Import path resolves.
- Synthetic sample imports.
- Missing external dataset is handled explicitly.
- Bad schema fails with a useful error.
- A real integration run records source, date, row count and file hash.

**PASS A2:** Stage 9 tests run from a clean checkout and distinguish offline tests from external-data tests.

## A3. Implement durable, idempotent Stage 1 storage

Replace or extend the in-memory-only store with SQLite (or another explicitly chosen durable database) while preserving a clean Python API.

Suggested tables:
- `fixtures`: stable fixture ID, competition, season, kickoff, home team ID, away team ID, status.
- `observations`: fixture ID, kind, payload, source, source record ID, event time, available_at, retrieved_at, content hash.
- `imports`: source URL, source version, retrieval time, file hash, parser version, row counts, validation result.
- `schema_migrations`: applied schema versions.
- `predictions`: fixture, model version, training cutoff, data snapshot, prediction timestamp, probability payload, feature provenance.
- `model_registry`: model version, artifact path/hash, status, metrics, training data cutoff.

Rules:
1. Stable fixture identity must include competition/league, season, date or kickoff, canonical home team and canonical away team. Do not identify a match by team names alone.
2. Store original source names as well as canonical team IDs.
3. Identical re-import: add zero duplicate observations.
4. Conflicting result for the same fixture: preserve source evidence, flag conflict and fail validation; never silently overwrite.
5. Database transactions must prevent partial imports.
6. Add unique constraints/indexes for stable IDs and source record identity.
7. Support database backup and restore.
8. Store JSON payloads with schema versions.
9. Provide explicit migration tests.
10. Keep raw source data and normalised observations traceable.

**Tests**
- Import 3 fixtures; close DB; reopen; all 3 remain.
- Import identical file again; zero new fixture/observation duplicates.
- Import same fixture with conflicting score; conflict recorded and import fails or quarantines row according to documented policy.
- Simulate process interruption; transaction rolls back.
- Migrate an older test database to latest schema.
- Backup and restore; fingerprints match.
- Two concurrent imports do not create duplicate fixture identities.

**PASS A3:** durable storage, migrations, transactions, idempotency, provenance and restore all pass.

## A4. Correct time and availability semantics

1. Store UTC timestamps with timezone information.
2. Store kickoff time separately from result availability.
3. A result becomes usable only when it was actually published/recorded as available.
4. If source data has only a match date and no final-whistle/publication time, use a conservative policy: result is unavailable to predictions earlier on that date and becomes eligible no earlier than the next day in the league's local timezone, unless reliable evidence supplies a later/earlier timestamp.
5. Convert source-local times using an explicit IANA timezone; do not assume UTC.
6. Snapshot queries must filter on `available_at <= as_of`.
7. Reject naive datetimes.
8. Make same-day ordering conservative: all fixtures from a date share the pre-date snapshot unless reliable kickoff and result-publication timestamps prove an ordering.

**Tests**
- Evening match result cannot appear in a same-day pre-match snapshot.
- Daylight-saving transitions are handled.
- Naive timestamp is rejected.
- Future observation is excluded.
- Snapshot is reproducible from the same database state and cutoff.

**PASS A4:** no result can leak into a prediction before it could have been known.

# 4. Phase B — Data source and historical dataset

## B1. Choose sources lawfully and realistically

Do not automatically scrape or train on a source without confirming its licence and terms. The earlier audit noted Football-Data.co.uk's stated restrictions on automated scraping/commercial or AI-training use. Obtain permission before using it for those purposes.

OpenFootball's football.json repository is a possible public-domain/CC0 historical results source, but it is not a guaranteed live feed and does not provide the full xG/injury/lineup dataset required for advanced features. Re-check the licence and terms at implementation time:
- https://github.com/openfootball/football.json
- https://github.com/openfootball/help
- https://www.football-data.co.uk/data

Source selection requirements:
- permitted use for the intended purpose;
- documented schema;
- source identity and retrieval date;
- historical coverage and known gaps;
- stable team/competition identifiers or a reliable mapping;
- timestamps sufficient for the features being tested.

If no permitted timestamped source exists for a feature, do not use that feature in the production model.

## B2. Build the results importer

1. Create a source adapter for the chosen results feed.
2. Download to a local raw-data directory outside version control by default.
3. Save URL, retrieval timestamp, response metadata, source revision and SHA-256.
4. Parse into a canonical schema.
5. Map team aliases using a reviewed mapping table; unknown teams must be surfaced for review, not guessed.
6. Validate league, season, dates, home/away teams, scores and match status.
7. Quarantine invalid rows with reasons.
8. Load valid rows into SQLite in a transaction.
9. Produce a machine-readable import report.

**Validation report must include**
- source and file hashes;
- seasons and date range;
- rows downloaded, parsed, accepted, rejected;
- duplicate and conflicting fixture counts;
- missing scores;
- unknown team names;
- home/away self-fixtures;
- count by season;
- exact import command and software version.

Do not assume every season has 380 matches: account for abandoned, postponed, incomplete or differently structured seasons.

## B3. Historical data acceptance

**Tests**
- Every accepted fixture has unique identity.
- Every completed match has valid nonnegative integer goals.
- No team plays itself.
- No duplicate completed fixture.
- All unknown aliases are resolved or quarantined.
- Importing the same raw file twice is idempotent.
- Re-running parser on identical raw bytes produces identical normalised output.
- Provenance and checksums are present.

**PASS B:** reproducible, licensed results dataset is imported and validated; all anomalies are documented.

# 5. Phase C — Mathematical engine and production Dixon–Coles

## C1. Validate Stage 2 score matrix

For independent Poisson rates lambda_home and lambda_away:
- both rates must be finite and strictly positive;
- rho must be finite and within an explicitly justified safe range;
- score grid size must be configurable;
- Dixon–Coles tau correction applies only to 0-0, 1-0, 0-1 and 1-1;
- every corrected cell must be nonnegative;
- finite-grid tail probability must be returned explicitly.

Do not silently renormalise a truncated score grid and then treat it as the full distribution. Either:
1. calculate sufficient grid size to make the tail smaller than a documented tolerance and account for tail mass; or
2. compute 1X2/BTTS/totals from exact/converged formulas with a documented error bound.

## C2. Validate derived markets

1. Home/draw/away probabilities must sum to 1 within a strict numerical tolerance.
2. BTTS and over/under calculations must handle tail mass correctly.
3. Exact score probabilities must be nonnegative and finite.
4. Total score-grid mass plus tail must equal 1 within tolerance.
5. Increasing max goals must converge to stable outputs.
6. Check edge cases with high and low goal rates.
7. Cross-check Stage 2 functions against the production predictor on fixed parameter fixtures.

## C3. Validate production Dixon–Coles maximum likelihood fitting

1. Identify the actual production fit/predict functions in `alea_predictor_v2_4_1.py` and the development candidate.
2. Preserve v2.4.1 as frozen benchmark.
3. Verify objective function, team attack/defence parameterisation, home advantage, rho, regularisation and time decay.
4. Use sensible identifiability constraints (e.g. centred attack/defence parameters or a reference team) so parameters cannot drift by a common offset.
5. Validate optimiser success, convergence status, finite parameters and gradient/tolerance diagnostics.
6. Bound pathological parameters and reject a failed fit rather than emitting probabilities.
7. Handle promoted/new teams with documented league priors and shrinkage, not unbounded estimates.
8. Test teams with zero goals scored/conceded and sparse histories.
9. Test save/load round-trip and model schema compatibility.
10. Verify predictions are deterministic for identical data, parameters and software version.

**Tests**
- Known synthetic dataset recovers plausible parameters.
- Zero-goal/sparse teams do not create extreme rates.
- Invalid optimiser result is rejected.
- rho corrections stay nonnegative.
- Probabilities sum to one.
- No NaN or infinity.
- Save/load predictions match within tolerance.
- Frozen reference file hash remains unchanged.

**PASS C:** independent mathematics and production implementation agree; production fits are stable and return valid probability distributions.

# 6. Phase D — Integrate features into one prediction pipeline

## D1. Create a single prediction interface

One public function/command should accept:
- fixture ID or fixture description;
- explicit prediction `as_of` time;
- selected champion model version;
- data-store connection.

It should:
1. load the fixture;
2. create the as-of snapshot;
3. build eligible features;
4. record missing/unavailable feature states;
5. fit/load the appropriate model trained only before the cutoff;
6. generate probabilities;
7. validate probabilities;
8. persist prediction plus provenance;
9. return a structured response.

Output should include:
- home/draw/away probabilities;
- expected goals and scoreline distribution where supported;
- optional BTTS/totals derived from the same distribution;
- model version and training cutoff;
- prediction timestamp;
- data snapshot hash;
- available and missing features;
- clear warnings when inputs are incomplete.

## D2. Elo feature

1. Calculate Elo chronologically from completed results only.
2. Choose and document initial rating, home advantage, K-factor and update rule.
3. Treat same-date matches conservatively unless kickoff ordering is verified.
4. Do not update ratings with the target fixture's outcome.
5. Handle promoted teams with a predeclared league-average prior and uncertainty/shrinkage.
6. Convert Elo differences to 1X2 probabilities with a mapping fitted only on training/validation data; do not assign a fixed draw probability such as 0.25.
7. Evaluate Elo as a standalone candidate and as an addition to Dixon–Coles.

**Tests:** no future match changes an earlier Elo; deterministic update order; promoted-team prior; correct draw mapping; same-day leakage prevention.

## D3. Recent form and head-to-head

1. Use only prior matches available by `as_of`.
2. Define windows before evaluation (e.g. last 5/10) and test sensitivity only inside training folds.
3. Consider opponent strength and home/away context.
4. Avoid giving head-to-head disproportionate weight when samples are tiny or squads/managers have changed.
5. Do not include a feature simply because it sounds useful; test its incremental value.
6. Compare form-only and DC+form on exactly the same fixtures.

## D4. xG features

1. Find a licensed xG source with historical coverage and, critically, timestamps showing when each xG value became available.
2. Store home and away xG for the relevant match.
3. Compute rolling xG for/against from prior matches only.
4. Keep match xG for the target match unavailable until after it has occurred.
5. Do not use a current season's revised historical xG as though it was known in real time unless the original publication timestamp is preserved.
6. If source lacks availability history, mark xG historical backtest as potentially revised/unsafe and do not use it for a strict real-time claim.
7. Test rolling windows and venue splits inside training only.
8. Compare DC+xG with DC baseline.

## D5. Injuries, suspensions and lineups

1. Obtain a licensed source with historical timestamped injury/suspension/lineup data.
2. Store player ID, team ID, status, effective period, source, confidence and available_at.
3. Distinguish confirmed, doubtful, returning and unverified reports.
4. Do not infer that an absent record means a player is fit.
5. Confirmed starting lineups can only be used after they are officially published and before kickoff.
6. Replace Stage 5's hand-authored player-impact stub with metadata-only output until a real impact model is trained.
7. If estimating player impact, estimate it from historical player/team data within each training fold; prevent post-event leakage.
8. Test whether player features add predictive value beyond DC, Elo and form.

## D6. Contextual features

For weather, referee, manager change, venue, travel, derby and similar features:
1. identify a source and licence;
2. capture the historical value and publication time;
3. define how missing data behaves;
4. check that the feature is known before prediction time;
5. implement it behind a feature flag;
6. evaluate it alone and incrementally;
7. disable it if it fails to improve held-out performance or is too sparsely available.

## D7. Ensemble and ML

1. Validate probability vectors and reject NaN/negative values.
2. Require unique fixture/model prediction records.
3. Align models on identical fixture sets before ensemble evaluation.
4. Reject negative, missing or non-finite weights.
5. Learn weights using training/validation data only.
6. Compare simple equal-weight ensemble against learned weights.
7. Train LightGBM/XGBoost only if there are enough licensed, timestamped features and data.
8. Use chronological nested validation and regularisation.
9. Compare against DC, Elo and simple baselines.
10. Do not include a complex learner just to tick a roadmap box.
11. If no reliable feature set exists, keep the simpler model as champion.

**PASS D:** one integrated prediction interface works; every enabled feature is leakage-safe, traceable, tested and independently evaluated.

# 7. Phase E — Stage 8 calibration

1. Generate strictly out-of-sample predictions from chronological folds.
2. Split calibration fitting from final holdout evaluation.
3. Compare no calibration, temperature scaling and suitable alternatives such as multinomial/Dirichlet calibration; use isotonic only where sample size supports it.
4. Fit calibrators on past/validation predictions only.
5. Evaluate class-wise reliability diagrams, calibration error with bin counts, log loss, Brier and RPS.
6. Avoid tiny bins and overinterpreting noisy calibration curves.
7. Preserve the uncalibrated output if calibration does not help.
8. Persist calibrator version and training window with model metadata.

**Tests**
- Calibrator is fitted without holdout outcomes.
- Probabilities remain valid and sum to one.
- Refit is deterministic.
- Calibration improves or does not materially damage predeclared metrics on later data.

**PASS E:** calibration is demonstrably useful or deliberately omitted with evidence.

# 8. Phase F — Stage 9 historical walk-forward evaluation

## F1. Freeze evaluation protocol

Before examining test outcomes, record:
- seasons/date range;
- initial training window;
- expanding or rolling window rule;
- test block length;
- minimum history;
- feature definitions;
- hyperparameter search space;
- primary and secondary metrics;
- calibration protocol;
- holdout boundary;
- acceptance thresholds.

## F2. Run the production baseline first

1. Fit production Dixon–Coles MLE only on past observations.
2. Predict the next chronological test block.
3. Store each prediction before joining the actual result.
4. Repeat for all test blocks.
5. Log training cutoff, model hash, data snapshot hash, fixture, probabilities and actual outcome.
6. Run leakage assertions.
7. Re-run from a clean checkout and compare results.

Do not treat an earlier crude fixed-draw Elo baseline as proof that production Dixon–Coles has been beaten.

## F3. Benchmark models

Evaluate on identical fixtures:
- league-frequency baseline;
- independent Poisson baseline;
- production Dixon–Coles;
- Elo alone;
- recent form alone;
- DC + Elo;
- DC + form;
- DC + Elo + form;
- xG and player/context variants only when data qualifies;
- bookmaker probabilities only if licensed and timestamped before kickoff.

## F4. Metrics

Report:
- multiclass log loss;
- multiclass Brier score, stating exact formula/convention;
- ranked probability score;
- accuracy and confusion matrix;
- class prevalence and prediction distribution;
- calibration/reliability by class and bin sample count;
- season-by-season results;
- paired bootstrap confidence intervals for differences;
- number of fixtures scored and excluded, with reasons.

Do not compare models on different fixture sets and call it a fair comparison. Do not use accuracy as the sole selection metric.

## F5. Feature ablation

For each candidate:
1. run baseline;
2. add one feature;
3. compare same fixtures and folds;
4. compute paired metric differences and uncertainty;
5. inspect season stability and calibration;
6. retain only if it improves the predeclared primary objective without material damage elsewhere;
7. record failed features as rejected/experimental rather than hiding them.

## F6. Final untouched holdout

1. Select the final model using training and validation only.
2. Freeze code, features, hyperparameters and calibrator.
3. Run the holdout exactly once.
4. Compare candidate against the frozen baseline.
5. Publish all metrics and uncertainty intervals, including disappointing results.
6. If improvement is inconclusive, keep the simpler baseline.

**PASS F:** reproducible walk-forward and final holdout reports exist for production DC and the chosen combined model, with no leakage and fair fixture alignment.

# 9. Phase G — Stage 10 automation and model lifecycle

## G1. Data refresh

1. Implement source adapters only for approved, documented feeds.
2. Add timeouts, retries, exponential backoff and rate-limit handling.
3. Validate response schema and source health.
4. Separate fixtures, completed results, odds, xG, lineups and injuries into distinct data kinds.
5. Make repeated updates idempotent.
6. Log every fetch, failure and rejected record.
7. Never treat a stale or failed feed as fresh.
8. If there is no dependable permitted live source, keep live automation off and document a manual import path.

## G2. Scheduled model updates

1. Train a candidate in an isolated run.
2. Validate on chronological data.
3. Compare to the champion under the predeclared promotion rule.
4. Promote only if acceptance criteria pass.
5. Keep the previous champion intact.
6. Save training data cutoff, code commit, dependency versions, parameters, metrics and artifact hash.

## G3. Model registry and rollback

1. Assign immutable model IDs.
2. Store artifact checksums.
3. Record champion/candidate/retired state.
4. Verify artifact integrity before loading.
5. Test rollback to prior champion.
6. Test corrupted model, incompatible schema and interrupted training.
7. Never overwrite a model that has already generated predictions.

**PASS G:** automation is repeatable, idempotent and safe; a bad candidate cannot replace the champion.

# 10. Phase H — Stage 11 interface and explanation

## H1. Prediction interface

Build a simple CLI or API first; do not start with a large UI.

Required functions:
- list upcoming fixtures from supported data;
- predict a selected fixture;
- inspect a previous prediction;
- show model/data freshness;
- show missing features and warnings;
- export prediction history.

Display:
- 1X2 probabilities;
- expected goals and likely scorelines where supported;
- BTTS/totals derived from the same score distribution;
- model version and timestamp;
- clear note that probabilities are estimates, not guarantees.

## H2. Explanations

1. Explain only features actually used by that prediction.
2. Distinguish measured inputs from estimates and missing inputs.
3. Never claim an injury or lineup fact if source data is unavailable.
4. Do not imply feature importance is causal.
5. Provide model-level explanation and per-fixture input summary.
6. Verify explanation values against stored feature snapshots.

## H3. Prediction history

Store:
- fixture ID and kickoff;
- prediction timestamp;
- model and calibrator versions;
- training cutoff;
- input snapshot hash;
- probabilities;
- feature availability/missingness;
- actual result once known;
- evaluation status.

**Tests:** retrieve historical prediction; reproduce it from stored artifacts; confirm later data changes do not mutate old predictions.

**PASS H:** usable prediction interface and immutable, reproducible prediction history.

# 11. Phase I — Stage 12 security, monitoring and resilience

## I1. Security
- Move API keys to environment variables or secret manager.
- Add .env and local raw-data/model paths to .gitignore.
- Scan current files and Git history for committed credentials.
- Rotate any exposed credentials; removing them from the latest file is not enough.
- Avoid logging secrets or personal tokens.
- Pin dependencies and review vulnerabilities.

## I2. Failure handling
Test:
- no internet;
- HTTP 429/rate limit;
- HTTP 500/upstream outage;
- malformed JSON/CSV;
- missing columns;
- unknown team;
- duplicate/conflicting results;
- database locked/full/corrupt;
- model missing/corrupt;
- training process interrupted;
- invalid probability vector;
- stale data;
- missing feature sources.

Expected behaviour: fail closed, preserve last known-good model and predictions, log actionable errors, and never fabricate data.

## I3. Monitoring
Track:
- last successful data refresh;
- source health;
- data age;
- missing-feature rates;
- prediction counts;
- model version;
- calibration/performance as outcomes arrive;
- distribution drift;
- model/data errors.

Do not auto-retrain/promote from a drift alert without validation.

## I4. Recovery
- scheduled database backups;
- artifact checksums;
- documented restore steps;
- rollback to last known-good champion;
- clean install and recovery drill.

**PASS I:** failure simulations do not corrupt history or replace the champion; recovery is demonstrated.

# 12. Phase J — Stage 13 acceptance and release

Stage 13 is not complete until all required phases have evidence.

Release checklist:
1. Clean clone installs successfully.
2. Offline tests pass.
3. Integration tests pass with licensed historical data.
4. Data import is idempotent and provenance-complete.
5. Production DC walk-forward passes leakage checks.
6. Candidate comparison uses identical fixtures and a final untouched holdout.
7. Calibration is validated or intentionally omitted.
8. Every active feature has a documented source, availability rule, test and evaluation result.
9. Unsupported features are disabled and labelled experimental/unavailable.
10. Prediction API/CLI produces traceable valid probabilities.
11. Model registry, backup and rollback tests pass.
12. Secrets scan is clean.
13. Documentation matches actual behaviour.
14. All reports state commit SHA, data hashes, test command and metrics.
15. Release candidate is reproduced from a clean checkout.
16. Only then tag and publish v3.0.0.

A stage report must never be manually marked PASS without linked test output or reproducible evidence.

# 13. Exact execution order

Do the work in this order; do not skip ahead:

1. **A1:** environment and clean test command.
2. **A2:** repair broken Stage 9 test paths and split offline/integration tests.
3. **A3:** implement SQLite persistence, migrations, idempotency and conflict handling.
4. **A4:** fix timestamps and snapshot availability semantics.
5. **B1–B3:** choose permitted results source, implement importer and validate historical data.
6. **C1–C3:** correct Stage 2 math and production Dixon–Coles fit.
7. **D1–D4:** connect data store, feature interface, production model and safe Elo/form features.
8. **E:** calibration.
9. **F:** production baseline walk-forward, feature ablations, combined model and untouched holdout.
10. **G:** add xG/player/context features only if suitable data is available and they pass ablation.
11. **H:** model registry, safe promotion and rollback.
12. **I:** prediction CLI/API, explanation and prediction history.
13. **J:** approved data refresh automation.
14. **K:** security, monitoring, backup and recovery.
15. **L:** final acceptance and release.

Each numbered item has a PASS gate above. If a gate fails, fix that phase before moving forward. If a feature's data source is unavailable or its evidence is negative, leave it disabled; do not block a sound results-only model by pretending the feature exists.

# 14. First concrete coding sprint

The first sprint is only Phase A. It should produce:

- a clean, reproducible offline test command;
- corrected Stage 9 test imports;
- a synthetic offline fixture dataset;
- SQLite-backed Stage 1 store with migrations;
- idempotent import and conflict detection;
- correct availability timestamps;
- unit tests for persistence, duplicate imports, conflicts, snapshots, timezone cutoffs and rollback;
- updated status report that reflects only what was actually run.

Do not train XGBoost, add more feature stubs, build a dashboard or automate live fetching during this sprint.

**Sprint exit condition:** a fresh clone passes all offline tests; the store persists across restarts; repeated imports do not duplicate records; conflicting records are surfaced; and no result is visible before its availability cutoff.

# 15. Reporting template for every phase

For each completed phase, record:

- phase and task ID;
- commit SHA;
- files changed;
- design decisions;
- data source and licence;
- exact commands executed;
- test names and pass/fail counts;
- integration dataset hash and row counts;
- metrics and confidence intervals where applicable;
- known limitations;
- evidence/artifact paths;
- PASS, FAIL or BLOCKED, with reason.

Do not use “complete” when only the interface or contract exists. Use precise labels:
- IMPLEMENTED — code exists;
- UNIT-TESTED — local behaviour verified;
- INTEGRATION-TESTED — components work together;
- EVALUATED — tested on chronological held-out data;
- ACCEPTED — all phase gates passed;
- BLOCKED — dependency/source/evidence unavailable.

---

## Final rule

Build a trustworthy, modest model first. A correctly evaluated Dixon–Coles + proven Elo/form system is better than an impressive-looking model full of unverified injuries, xG, context and machine-learning features. The goal is not to make every planned feature appear in ALEA. The goal is to make every feature that remains earn its place through evidence.
