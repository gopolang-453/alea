# ALEA 3.0 — Stage 13 repair and acceptance plan

**Branch:** `repair/stage13-evidence-and-pipeline`  
**Baseline commit audited:** `e6c2e55a7ed5d5df338c669125a11ab89a31508a`  
**Status:** Audit and repair specification only. No implementation or test is claimed complete by this document.

## 1. Release rule

ALEA 3.0 is not releasable until the production predictor, data pipeline, backtest, feature evaluation, and recovery path work together from a clean checkout. A unit-test count or a status-file checkbox is not acceptance evidence.

Keep `alea_predictor_v2_4_1.py` frozen. Keep `dev/alea_predictor_dev.py` as a candidate until it passes the same test protocol on a genuinely untouched time period. Never overwrite the frozen baseline to make the candidate look better.

A feature is retained only if it improves a predeclared primary metric on validation data and does not cause unacceptable regressions in secondary metrics or season-level performance. If it does not pass, disable it and document the rejection. No accuracy target, profitability claim, or guaranteed improvement is assumed.

## 2. Audit findings that must be resolved first

### P0 — Stage 9 test is not runnable from the committed tree

`stages/stage9/tests/test_stage9_1_real_data.py` imports from `stages/alea_stage1/persistent_store.py` and expects `stages/data/epl/E0_*.csv`. Neither that package nor those data files exists in the current Git tree. The committed Stage 1 module is `stages/stage1/data_store.py`, which exposes a different in-memory API. The report's 1,900-row import claim therefore cannot be reproduced from the committed files as they stand.

**Repair:** replace the stale imports with the actual supported Stage 1 interface, or implement and commit the missing persistent store with explicit schema/migrations. Do not silently keep two competing Stage 1 APIs. Keep raw third-party CSVs out of the repository unless their redistribution terms explicitly permit it; tests should accept a user-supplied data directory and use a small synthetic fixture in CI.

### P0 — Stage 1 duplicate and availability semantics are unsafe

In `stages/stage1/data_store.py`, `DataStore.add()` appends every record and has no uniqueness/idempotency check. `ingest_results_frame()` marks every result available at midnight UTC plus three hours, although the source rows contain a match date but not a verified final-whistle/publication timestamp. That timestamp can be earlier than the actual match completion and is not a defensible historical information-availability time.

**Repair:**
- Define a stable record identity: source + source record ID where available; otherwise kind + fixture key + metric/source identity + version.
- Make ingestion idempotent and detect conflicting revisions instead of silently duplicating or overwriting.
- Store distinct `kickoff_at`, `event_ended_at`, `published_at`, and `available_at` fields where available. Never infer a precise publication time from a date-only CSV.
- For date-only historical results, use a conservative rule: a result is not eligible until the next calendar day in the competition timezone, or mark its availability as unknown and exclude it from any test requiring intraday decisions. Document the selected rule.
- Preserve timezone-aware UTC instants and the original source date/time. Do not localize a naive midnight as if it were a verified kickoff.
- Add database uniqueness constraints and transaction-safe upserts in the persistent store.

### P0 — Two different backtest tracks are being conflated

`ALEA_3.0_COMPLETE_STATUS_REPORT.md` reports 1,900 matches / 1,600 predictions using a fast rates model and a crude fixed-draw Elo conversion. `DEV_REPORT.md` and `FULL_AUDIT.md` report a separate 1,140-match comparison of frozen v2.4.1, the development MLE candidate, and Bet365 closing prices. They are different samples, protocols, and model implementations. They must not be merged into one performance claim.

**Repair:** create one canonical evaluation runner and one machine-readable result schema. Each run must record dataset hash, row count, date range, source, model commit/version, model configuration, fold boundaries, cutoff rule, calibration status, metrics, and benchmark alignment. Reports must be generated from those artifacts, not manually transcribed.

### P1 — The production MLE model has not passed a full historical walk-forward

The complete report explicitly says the production `alea_predictor_v2_4_1.py` MLE was too slow for the 1,900-match run. The development report separately shows the regularized development copy, but its reported interval for log-loss improvement over v2.4.1 includes zero and Brier/RPS do not improve. The development candidate is therefore a numerical repair candidate, not a proven superior model.

**Repair:** benchmark runtime first; profile fitting; cache only computations that are mathematically invariant within a training window; use deterministic warm starts from the previous chronological fold only if the fit remains strictly confined to that fold's training data; and add convergence/finiteness diagnostics. Do not replace exact MLE with the fast rates model under the same label. Evaluate frozen v2.4.1 and the development candidate side-by-side on identical folds.

### P1 — Feature contracts are not equivalent to usable predictive features

Stages 4–6 mostly define feature accessors/stubs. In particular, Stage 5's `player_impact_stub()` assigns hand-written positional weights; it is not a fitted player impact model. Stage 6 functions can return context fields, but no evidence establishes that these features improve predictions. Stage 7 is ensemble scaffolding, not a trained ML model.

**Repair:** keep every unvalidated feature out of production predictions by default. Add source adapters only after source terms, timestamp semantics, coverage, and historical availability are documented. Evaluate one feature family at a time. A missing feature must be represented explicitly as missing, not as a zero that looks like a measured value.

### P1 — External data licensing is a product blocker

Football-Data.co.uk describes its free historical data as intended for private individuals and not for commercial or data-training products using automated bots/scrapers/AI. ALEA must not assume that free download means permission to train or operate a commercial AI product on that data.

**Repair:** use the existing data only within the permissions actually granted, seek written permission for any commercial/AI use, or select a provider whose licence explicitly covers model training, storage, derived features, redistribution (if needed), and commercial deployment. Record licence/source metadata per dataset. Do not automate downloads until terms permit it.

## 3. Canonical implementation sequence

### Step A — Make the repository reproducible

1. Add a supported Python version and pin tested dependency ranges in a lock/constraints file.
2. Add a single documented package layout; remove stale import paths and duplicate module conventions.
3. Add a clean-checkout test command that does not require private local files or internet access.
4. Add CI to run the frozen v2.4.1 suite, development-candidate suite, Stage 1–12 unit tests, lint/type checks, and a small deterministic integration test.
5. Add a test-data policy: synthetic fixtures in CI; real data supplied locally and never committed unless licensed.

**PASS:** a fresh clone installs from documented commands and all offline tests pass. CI must fail on missing modules/data rather than silently skip them.

### Step B — Repair Stage 1 data store and ingestion

1. Define schemas for fixtures, results, odds, xG, lineups, injuries, and contextual records.
2. Add stable fixture IDs and canonical team aliases with collision tests.
3. Add idempotent transactional ingestion and explicit update/revision behavior.
4. Validate required columns, dates, scores, team names, impossible fixtures, duplicate keys, and source-specific parsing.
5. Preserve source provenance and availability timestamps; fail closed when the source cannot establish the time a feature became available.
6. Add migrations, indexes, database backup, and restore tests.

**Tests:** same file imported twice adds zero records; changed source row creates a traceable revision; conflicting duplicate is rejected/reported; timezone conversion round-trips; unknown publication time is not treated as known before kickoff; snapshot excludes every record with `available_at > as_of`.

**PASS:** import/re-import/reopen/restore all reproduce the same fingerprint and fixture count, with a machine-readable validation report.

### Step C — Establish a valid historical dataset

1. Select seasons and a source with documented permission for the intended use.
2. Verify match counts against the official league schedule for each season; do not hardcode 380 for seasons affected by exceptional circumstances without checking.
3. Validate unique fixture identities, chronological order, postponed matches, promoted/relegated clubs, renamed teams, missing values, and score/result consistency.
4. Preserve odds columns separately from model input features. Odds may be used as a benchmark only when the odds timestamp is no later than the prediction decision time.
5. Produce a dataset manifest with SHA-256, source, licence, season coverage, schema version, row counts, exclusions, and timestamp assumptions.

**PASS:** a second import is idempotent; every exclusion is explained; no unlicensed dataset is used for a commercial/training claim.

### Step D — Run the true production Dixon–Coles baseline

1. Use the actual production `fit_model` / prediction path, not the Stage 2 score-matrix demonstration or a substitute rates model.
2. Use expanding-window chronological evaluation grouped by match date. No match on a test date may appear in training when the cutoff policy excludes same-day results.
3. At each decision cutoff, tune `xi` and regularization using training data only. Keep tuning nested inside the training window.
4. Record optimizer success, convergence, gradient/numerical checks, parameter bounds, training rows, cutoff, and prediction provenance.
5. Check all scoreline cells are finite/nonnegative, score-grid tail is accounted for, and 1X2 probabilities are finite, positive where mathematically expected, and sum to one.
6. Re-run the identical experiment and compare the saved prediction artifact byte-for-byte or within a documented floating-point tolerance.

**Metrics:** multiclass log loss (primary), multiclass Brier and ranked probability score (secondary), accuracy (descriptive only), calibration/reliability by class and probability bin, and scoreline/goal-distribution diagnostics.

**PASS:** the true production predictor completes all folds without leakage, non-convergence, invalid probabilities, or unexplained dropped matches. Save predictions and the complete run manifest.

### Step E — Compare the development numerical repair fairly

1. Run v2.4.1 and `alea-dc-dev` on exactly the same fixtures, cutoffs, and available inputs.
2. Keep all hyperparameter selection inside each training window.
3. Report paired per-match loss differences and confidence intervals using a date/round-aware block bootstrap, not an independent-row bootstrap that ignores matchday dependence.
4. Report each season and home/draw/away class separately.
5. Treat a fix that only removes pathological near-zero probabilities as a reliability repair; do not claim a stronger model unless multiple predeclared metrics and untouched data support it.

**PASS:** no candidate is promoted based solely on the same matches used to discover or tune the repair. The untouched future season remains a prospective test.

### Step F — Rebuild Stage 9.4–9.5 feature experiments

For each candidate (Elo, recent form, xG, player availability, contextual data), run:

1. Baseline predictions.
2. Baseline + exactly one feature family.
3. The same folds and the same fixtures, with paired metrics.
4. Missingness/coverage analysis and a missing-data ablation.
5. Per-season and per-class checks.
6. Feature availability/cutoff perturbation test: changing future feature records must not change earlier predictions.

Elo must be converted to 1X2 probabilities using a trained/validated mapping or a coherent score model; a fixed 0.25 draw probability is only a diagnostic baseline, not final ALEA output. Form windows must be calculated strictly from matches completed and available before the cutoff. xG/player/context sources require historical publication/availability timestamps. Hand-coded player impact values must not be described as measured player impact.

**PASS:** keep a feature only if it improves the predeclared primary metric on validation data, is not materially worse on secondary metrics, has sufficient coverage, and does not create a serious season/class regression. Otherwise mark it experimental/rejected.

### Step G — Calibration and model selection

1. Generate calibration predictions out of sample from the training/validation period only.
2. Fit temperature scaling or another calibration method only on a calibration split that precedes the final holdout.
3. Compare log loss, Brier, classwise reliability diagrams, and calibration curves. Brier alone is not a pure calibration measure.
4. Freeze the calibration transform before the untouched holdout.
5. Compare candidate, baseline, and de-vigged market benchmark on identical decision timestamps.

**PASS:** calibration is retained only if it improves the chosen probability-quality objective without damaging other metrics; otherwise use no calibration and record the result.

### Step H — Complete Stage 10 automation safely

1. Build a fixture/results updater behind a provider interface with retries, timeouts, rate limits, schema validation, and provenance.
2. Make every update idempotent and transactional.
3. Separate fixture updates, final-result updates, odds updates, and optional feature feeds.
4. Schedule training only after new data is validated.
5. Train a candidate in isolation; compare it with the current champion on a fixed validation protocol.
6. Promote only when acceptance criteria pass; otherwise retain champion and log rejection.
7. Add rollback and immutable model/prediction version records.

**Tests:** API timeout, 429, 500, malformed payload, missing match, changed result, duplicate response, delayed correction, interrupted training, failed promotion, and rollback. No provider failure may silently become zero-valued features.

**PASS:** an end-to-end dry run can update, validate, train, compare, promote/reject, and recover without manual database edits.

### Step I — Complete Stage 11 interface and explanation integrity

1. Show 1X2 probabilities, expected goals/scoreline outputs, BTTS and totals only when the underlying model supports them.
2. Display model version, prediction timestamp, data cutoff, and freshness.
3. Label each fact as confirmed, estimated, unavailable, or stale.
4. Generate explanations from actual feature contributions/inputs; never invent reasons.
5. Persist the exact input snapshot and model artifact reference so a historical prediction can be reproduced.

**PASS:** every displayed number matches the stored prediction record and can be independently regenerated.

### Step J — Complete Stage 12 reliability and security

1. Keep API keys out of source, test fixtures, logs, and reports.
2. Add dependency and secret scanning in CI.
3. Validate model files and datasets with hashes; reject corrupted or incompatible versions.
4. Test database backup/restore and model rollback.
5. Add structured logs, health checks, data freshness alerts, model drift monitoring, and failure alerts.
6. Document a clean install and disaster recovery.

**PASS:** all failure-injection tests recover or fail safely; no silent fallback produces fabricated predictions.

### Step K — Stage 13 final acceptance

Stage 13 can pass only when all of the following evidence exists:

- Clean-checkout CI green.
- Frozen baseline remains unchanged and hash-verified.
- Production Dixon–Coles walk-forward complete and reproducible.
- Development candidate compared fairly on identical folds.
- Combined model tested with nested chronological validation and untouched holdout.
- Every retained feature has real-source, availability-time, coverage, and ablation evidence.
- Calibration decision documented.
- Market benchmark uses correctly aligned odds timestamps.
- Automation, promotion, rollback, interface, monitoring, and recovery integration tests pass.
- Data licensing is appropriate for the intended deployment.
- Limitations and model version are documented in a generated release report.

Only then create a release candidate. Do not create `v3.0.0` until acceptance is signed off.

## 4. Required artefacts

The implementation should produce, not hand-edit:

- `reports/data_manifest.json`
- `reports/backtest_manifest.json`
- `reports/predictions_oos.csv` (or Parquet)
- `reports/metrics_by_model.json`
- `reports/metrics_by_season.json`
- `reports/paired_comparison.json`
- `reports/calibration.json`
- `reports/feature_ablation.json`
- `reports/reliability_test_results.json`
- `reports/FINAL_ACCEPTANCE.md`

Every artefact must include the commit SHA, dataset fingerprint, protocol version, and generation timestamp.

## 5. External references

- Football-Data historical results/odds page and data notes: https://www.football-data.co.uk/data
- Premier League season CSV listings: https://www.football-data.co.uk/englandm/premier-league
- scikit-learn time-ordered validation: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- scikit-learn probability calibration and scoring-rule caveats: https://scikit-learn.org/stable/modules/calibration.html
- scikit-learn Brier score definition: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html

**Important data-use note:** Football-Data.co.uk states that its free data is intended for private individuals and not commercial or data-training products using automated bots/scrapers/AI. Obtain written permission or use a suitably licensed source before any commercial AI training/deployment.
