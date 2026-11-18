# ALEA 3.0 — Verified remediation plan

**Audit date:** 18 November 2026  
**Repository:** `gopolang-453/alea`  
**Audited branch:** `main`  
**Purpose:** turn the current collection of code, reports, and partial experiments into a reproducible, leakage-safe, testable release. This is a work plan, not a claim that the work is already complete.

---

## 1. Release decision

**Do not release ALEA 3.0 yet. Do not replace the frozen v2.4.1 predictor yet.**

The repository contains useful foundations and experiments, but its current reports overstate how much can be reproduced from the checked-in tree. A report is evidence only when the referenced code, data provenance, commands, and outputs are present and independently rerunnable.

The development candidate's regularisation repair is worth preserving, but its reported comparison against v2.4.1 is inconclusive and it remains behind the Bet365 closing-price benchmark in the reported sample. The Stage 9 fast-rate/Elo results are exploratory, not proof that the production Dixon–Coles maximum-likelihood predictor or a combined model is better.

## 2. Findings from the repository audit

The following are concrete repository observations, not assumptions:

1. `stages/stage9/tests/test_stage9_1_real_data.py` imports `stages/alea_stage1/persistent_store.py` and expects files under `stages/data/epl/`. Those paths are not present in the audited `main` tree.
2. The checked-in Stage 1 implementation is `stages/stage1/data_store.py`. It defines an in-memory `DataStore`; it does not define the `PersistentDataStore` or `ingest_csv` names imported by the Stage 9.1 test.
3. `DataStore.add()` appends records without duplicate-key protection. Therefore duplicate-safe persistent ingestion is not demonstrated by this implementation.
4. `ingest_results_frame()` estimates result availability as match-date midnight UTC plus three hours. That is not a reliable actual result-publication timestamp and can place a result before the match has finished. It must not be used as a historical information-availability clock.
5. The Stage 9 test's claimed five CSV files are not present in the audited tree. The report's 1,900-row result is therefore not independently reproducible from the repository as checked out.
6. `STAGE10_STATUS.md` refers to `stages/stage10/automation.py`, but no `stages/stage10/` directory or that module appears in the audited tree.
7. `STAGE9_BACKTEST_REPORT.md` explicitly says the reported walk-forward used a fast rates model and Stage 2 score matrix, not the production `alea_predictor_v2_4_1.py` MLE. It also says the combined model (9.5) was not run.
8. The repository contains a separate development audit. It documents a genuine `reg = 0` unbounded-fit failure in v2.4.1 and a repair in `dev/alea_predictor_dev.py`, but reports that the development candidate's improvement over v2.4.1 is not statistically conclusive and that it remains behind Bet365 closing prices on that sample.
9. The top-level status reports are not fully aligned. The older final report says no real-data comparative evaluation was run; the newer complete report includes a fast-rate/Elo experiment. The newer report should supersede the older one only after its supporting experiment is committed and reproducible.

**Immediate consequence:** first repair the repository's reproducibility and evidence chain. Do not add more features or mark stages complete to compensate for missing evidence.

## 3. Non-negotiable engineering rules

- Keep `alea_predictor_v2_4_1.py` unchanged as the frozen reference until a candidate passes the release gates.
- Keep development work isolated from the reference implementation. Every candidate gets a distinct version identifier and model-file format/version.
- Never train, tune, calibrate, select features, or choose thresholds using the final holdout period.
- Split by kickoff date, not random rows. All matches on the same date belong to the same test block.
- At prediction time, every feature must have an auditable `available_at` timestamp no later than the prediction cutoff.
- A match's final score must never become available before the match is complete. Match date alone is not a publication timestamp.
- Missing or stale inputs must be represented as missing; do not fabricate xG, injuries, lineups, or context.
- Keep raw source files immutable and record source, retrieval time, file hash, schema version, and licence/permission.
- Report log loss, multiclass Brier, RPS, accuracy, calibration, sample size, and uncertainty together. Accuracy alone is not an acceptance metric.
- Compare against at least the frozen ALEA reference and a de-vigged market benchmark when valid, time-aligned odds are available.
- No staking or value recommendations are enabled by this engineering roadmap. The development audit reports negative historical ROI for the current value-engine filter.

## 4. Work sequence and acceptance gates

### Gate 0 — Freeze and establish a clean baseline

**Tasks**
1. Record the exact `main` commit SHA and SHA-256 hashes of the reference predictor, value engine, and existing model artefacts.
2. Tag or otherwise preserve the current reference state. Do not rewrite its history.
3. Create a clean development branch for remediation.
4. Record Python and dependency versions and make a reproducible environment file.
5. Run the existing v2.4.1 test suite from a clean checkout and preserve the full output.

**Tests**
- The reference predictor's source hash is unchanged.
- Every existing test is listed with its command, exit code, and duration.
- A second clean run gives the same test outcome.

**PASS:** reference preserved and baseline suite reproducible.  
**FAIL:** stop and repair environment/test discovery before changing model behaviour.

### Gate 1 — Repair Stage 1 data storage and availability semantics

**Tasks**
1. Decide on one canonical Stage 1 API. Either implement the persistent store and CSV importer that the Stage 9 test expects, or rewrite the test to use the actual Stage 1 API. Do not maintain two incompatible store implementations.
2. Implement durable storage with a unique fixture/source-record key and transactional inserts.
3. Make re-import idempotent. Define how corrected source rows are versioned rather than silently duplicated or overwritten.
4. Store timestamps in UTC with timezone-aware parsing. Keep distinct fields for kickoff time, match completion time, source publication/collection time, and system ingestion time.
5. Do not infer result availability from date + a fixed offset. If a historical source does not provide the actual publication time, document a conservative availability policy and test that it never exposes a result before the match could have finished.
6. Validate required columns, date parsing, non-negative integer scores, team names, fixture identity, duplicate collisions, and impossible self-fixtures.
7. Preserve the original source row and a hash for provenance.

**Tests**
- Import the same file twice: second import adds zero new records.
- Import a corrected row: it creates a traceable revision and does not erase history.
- Reopen the database: row counts and fingerprints remain stable.
- A snapshot before full-time cannot see the final score.
- A snapshot after the declared publication time can see it.
- Naive timestamps, malformed dates, negative goals, missing teams, and duplicate fixture keys fail closed.

**PASS:** persistent, idempotent, auditable store with tested time-travel snapshots.  
**FAIL:** no backtest may use this store.

### Gate 2 — Make historical data reproducible and legally usable

**Tasks**
1. Select the source for each data type separately: results, odds, xG, injuries, lineups, and fixtures.
2. Record the source's licence and permitted use before automating downloads or committing raw data.
3. For football-data.co.uk, preserve source attribution and check its stated usage restrictions. Do not assume its free CSV data is licensed for a commercial AI/data-training product or automated scraping. Obtain permission or choose a source whose terms allow the intended use.
4. Store raw data outside generated prediction outputs; provide a documented download/import command.
5. Pin dataset versions using checksums and a manifest. Never silently update a historical dataset and then compare scores as if it were the same experiment.
6. Document missing values and season/team coverage.

**Tests**
- Dataset manifest lists every file, hash, season, row count, source, retrieval time, and licence note.
- Re-downloading/re-importing the same version reproduces the same canonical rows.
- Team aliases and promoted/relegated clubs are handled consistently.
- Missing columns or changed source schemas stop the import with a clear error.

**PASS:** every historical result in a reported experiment can be traced to a versioned, permitted dataset.  
**FAIL:** do not publish performance claims based on undocumented or unauthorised data.

### Gate 3 — Build a single reproducible Stage 9 backtest runner

**Tasks**
1. Add one documented command that loads a dataset manifest, creates chronological date blocks, fits the selected model using only earlier matches, and writes immutable prediction rows.
2. Use the production Dixon–Coles MLE implementation as a separate baseline candidate; do not label the fast rates approximation as production MLE.
3. Use expanding-window evaluation. Specify minimum training history, refit frequency, time decay, regularisation search, and team-prior policy before running.
4. Group all fixtures on the same date into one test block. Enforce training cutoff strictly before the earliest test kickoff/date in that block.
5. Save each prediction with fixture key, kickoff, prediction timestamp, training cutoff, model version, data fingerprint, feature availability cutoff, parameters, and H/D/A probabilities.
6. Validate probabilities are finite, within [0,1], and sum to one within a strict tolerance. Validate score-grid mass and tail handling.
7. Save failures and skipped fixtures with explicit reasons. Never silently drop them.

**Tests**
- Synthetic fixture with a deliberately future result proves leakage is blocked.
- Same inputs/configuration produce identical predictions.
- Shuffling input row order does not change predictions.
- Every prediction's training cutoff precedes its test block.
- All same-day matches stay in the same block.
- Probability and score-grid invariants pass.
- The runner can reproduce a small checked-in synthetic fixture dataset without network access.

**PASS:** the runner is deterministic, leakage-safe, and auditable.  
**FAIL:** no performance comparison is accepted.

### Gate 4 — Re-establish honest model baselines

**Models to compare on identical test fixtures**
1. League/base-rate benchmark.
2. Independent Poisson attack/defence baseline.
3. Frozen ALEA v2.4.1 production Dixon–Coles MLE.
4. Development candidate with the regularisation repair.
5. Market benchmark from time-aligned, de-vigged odds, where licence and timestamps permit.

**Metrics**
- Multiclass log loss.
- Multiclass Brier score, with the exact convention stated.
- Ranked Probability Score.
- 1X2 accuracy as a secondary metric.
- Reliability diagrams and class-specific calibration summaries.
- Goal-score distribution diagnostics and tail mass.
- Paired date-block bootstrap confidence intervals for score differences.
- Results by season and by outcome class.

**Tests**
- Hand-calculated metric fixtures validate metric implementations.
- Label order is explicitly H, D, A everywhere.
- No probabilities are rounded before scoring.
- Market odds are demonstrably available at the model's prediction time.
- Market overround is removed with a documented method; invalid/missing prices are excluded with counts reported.

**PASS:** baseline report is regenerated from committed code/configuration and exact data hashes.  
**FAIL:** do not compare a new feature against numbers produced by a different sample or protocol.

### Gate 5 — Repair and validate the production MLE candidate

**Tasks**
1. Port the `reg = 0` guard and finite-strength checks from the development candidate only after reviewing the exact diff and adding regression tests.
2. Do not blindly adopt a regularisation value. Select regularisation only inside each training window or freeze it using a development period that is separate from the final holdout.
3. Check optimiser convergence, parameter bounds, identifiability constraints, and failure handling.
4. Check Dixon–Coles τ factors remain positive for all corrected scorelines and fitted rates.
5. Ensure low-score correction and score-grid truncation do not create negative, missing, or unnormalised probabilities.
6. Profile runtime and numerical stability. Optimise with caching/vectorisation only if results remain numerically equivalent.

**Tests**
- Zero-scoring/zero-conceding teams cannot produce unbounded strengths.
- Promoted/new teams receive documented priors and shrinkage.
- Extreme but valid score histories do not create near-zero result probabilities without evidence.
- Optimiser failure is surfaced, not silently accepted.
- Saved model reload gives identical predictions.
- Reference implementation remains unchanged.

**PASS:** candidate is numerically stable and completes the full chronological backtest.  
**FAIL:** keep it as a development branch only.

### Gate 6 — Re-test Elo and recent form correctly; then test combined model

**Tasks**
1. Replace the crude fixed 0.25 draw conversion with a principled, training-only mapping from Elo difference to three-way probabilities (or use Elo as a covariate in a fitted multinomial/goal model).
2. Fit any mapping only on the training portion of each walk-forward fold.
3. Test Elo alone, form alone, and Elo + form against the same fixtures as the production DC baseline.
4. Evaluate a combined DC + Elo/form model only if each input is generated using information available before kickoff.
5. Keep feature selection inside nested chronological training/validation; never use the final holdout to decide which features survive.
6. Use paired uncertainty intervals and report seasonal stability. A small point estimate improvement with an interval crossing zero is not a proven gain.

**Tests**
- Elo ratings update only after the match result becomes available.
- Form windows exclude the target match and all future matches.
- New teams and promoted teams have documented initial ratings.
- The H/D/A probability mapping is trained only on earlier predictions/results.
- Ablation tests show the marginal effect of each feature.

**PASS:** retained features improve proper scoring rules on unseen chronological data without material calibration or season-level degradation.  
**FAIL:** remove the feature or label it experimental; do not force it into the ensemble.

### Gate 7 — Add xG, player, lineup, and context features only with real historical availability data

**Tasks**
1. Choose a source with sufficient historical coverage and appropriate use rights for each feature.
2. Preserve when each item was published/known, not merely the date of the match.
3. Build a feature-availability audit: percentage of fixtures with usable values, missingness by season/team, and source freshness.
4. Test xG only if historical pre-match predictors can be built from prior matches' xG; never use the target match's post-match xG.
5. Test injuries/lineups only when the historical announcement timestamp is known. A final confirmed lineup cannot be used for a prediction timestamp before lineup publication.
6. Treat weather, referee, manager, travel and derby variables as hypotheses. Evaluate one at a time and run ablations.
7. Keep missingness explicit. Do not replace unavailable values with fabricated neutral values unless the model has a trained and validated missing-data mechanism.

**Tests**
- For every feature, construct a future-information leakage test.
- Remove the feature source and confirm the pipeline fails closed or produces a documented missing-feature state.
- Check data coverage and sample-selection bias.
- Compare baseline vs baseline+one feature on identical fixtures.

**PASS:** feature earns its place through out-of-sample improvement and availability audit.  
**FAIL:** do not include it in production predictions.

### Gate 8 — Probability calibration

**Tasks**
1. Generate strictly out-of-sample predictions from the selected candidate.
2. Fit calibration using only a chronological calibration window before the final holdout.
3. Compare no calibration, temperature scaling, and a suitable multiclass calibration method.
4. Evaluate log loss, Brier, RPS, and reliability by class. Do not interpret Brier alone as a pure calibration measure.
5. Freeze the calibration transform and apply it once to the final holdout.

**Tests**
- Calibration parameters never see holdout outcomes.
- Probabilities remain valid and sum to one.
- Calibration improves or preserves proper scoring rules and improves reliability in a meaningful, documented way.

**PASS:** calibration has measurable benefit and is frozen.  
**FAIL:** keep raw probabilities; do not add calibration just because the stage exists.

### Gate 9 — Automation and model governance

**Tasks**
1. Implement a provider interface for fixture and result feeds, with retries, timeouts, rate limits, and schema validation.
2. Keep manual CSV import as a supported fallback.
3. Schedule updates only after data-source terms permit automated use.
4. Make fetches idempotent and preserve source revisions.
5. Train candidate models in an isolated job; never overwrite the champion model during training.
6. Promote only when a predeclared evaluation gate passes on a validation period and all safety checks pass.
7. Keep champion/candidate metadata, data hash, code commit, metrics, calibration, and training cutoff.
8. Implement rollback and backup restore; log all state transitions.

**Tests**
- API timeout, outage, malformed payload, rate limit, and missing fixture are simulated.
- Re-running a fetch does not duplicate records.
- A deliberately worse candidate is rejected.
- Failed training cannot corrupt the champion.
- Rollback restores the exact prior model and reproduces its predictions.

**PASS:** a controlled pipeline can update data, train, evaluate, promote, and roll back without human intervention beyond configured approval.  
**FAIL:** keep automation disabled and use manual, reviewed releases.

### Gate 10 — Prediction interface, security, monitoring, and release

**Tasks**
1. Build the interface only after the prediction API is stable. Display H/D/A probabilities, scoreline distribution, xG, BTTS and totals only when actually produced by the model.
2. Show model version, prediction timestamp, data freshness, missing inputs, and whether lineups are confirmed or unavailable.
3. Store immutable prediction records so a past forecast can be reproduced.
4. Keep secrets out of source control; use environment secrets and rotate any exposed credentials.
5. Monitor provider freshness, missingness, model errors, calibration drift, and score degradation.
6. Document installation, data permissions, reproducible commands, limitations, and incident recovery.
7. Run the full test suite and a clean-install smoke test.
8. Freeze the release candidate, publish evaluation artefacts, and tag v3.0.0 only after all gates pass.

**Tests**
- Displayed values exactly match stored model outputs.
- Old predictions remain reproducible after a new model is promoted.
- Secret scan finds no keys/tokens.
- Missing/stale data is visibly flagged.
- Clean install and documented test commands pass.
- Monitoring alerts on stale data and material performance degradation.

**PASS:** all required gates are green, evidence is committed, and the release can be reproduced.  
**FAIL:** Stage 13 remains open.

---

## 5. Required repository structure after remediation

A practical target layout:

```text
alea/
  alea_predictor_v2_4_1.py       # frozen reference
  dev/
    alea_predictor_dev.py        # isolated candidate
  stages/
    stage1/                      # canonical persistent store + schema
    stage2/                      # score model mathematics
    stage3/                      # Elo and form features
    stage4/                      # xG feature pipeline
    stage5/                      # player/lineup features
    stage6/                      # contextual features
    stage7/                      # ensemble contracts and fitted models
    stage8/                      # calibration
    stage9/                      # backtest runner, metrics, leakage checks
    stage10/                     # data updater and model governance
    stage11/                     # prediction API/interface
    stage12/                     # reliability/security/recovery
    stage13/                     # final acceptance checklist
  tests/
    unit/
    integration/
    backtest/
    fixtures/                    # small synthetic fixtures only
  data/
    README.md                    # instructions and licensing; raw data not blindly committed
    manifests/
  reports/
    backtests/
    release/
  .github/workflows/
    tests.yml
  requirements.txt
  README.md
  ALEA_3.0_REMEDIATION_PLAN.md
```

Do not create empty directories just to make this layout look complete. Add each module when it has working code and tests.

## 6. Exact next implementation order

1. **Repair Stage 1 / Stage 9 path mismatch.** Make the Stage 9.1 test import the actual canonical store and use a small synthetic CSV fixture committed to the repo. Add the persistent store/importer that the real-data report claims, or correct the report if it was run from uncommitted local files.
2. **Fix availability timestamps and duplicate handling.** This is a correctness blocker, not optional cleanup.
3. **Make the 1,900-match experiment reproducible.** Provide a data manifest and permitted data acquisition instructions; do not claim PASS until a clean checkout can run it.
4. **Implement and run the production MLE walk-forward.** Keep it separate from the fast-rate approximation.
5. **Re-test Elo/form with a fitted draw mapping and run Stage 9.5 combined ablation.**
6. **Run the final untouched holdout once, after freezing all choices.**
7. **Only then implement the remaining live automation, interface, monitoring, and release work.**

At every step: implement → add a regression test → run targeted tests → run the full suite → record exact command, commit SHA, dataset hash, and result. A stage advances only on a reproducible PASS.

## 7. External methodological references

- Dixon & Coles, *Modelling Association Football Scores and Inefficiencies in the Football Betting Market*: https://doi.org/10.1111/1467-9876.00065
- Football-Data downloads and notes: https://football-data.co.uk/downloadm.php
- Football-Data data and use notes: https://football-data.co.uk/data
- scikit-learn calibration guide: https://scikit-learn.org/stable/modules/calibration
- scikit-learn log loss: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.log_loss.html
- scikit-learn Brier score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html

**Final rule:** ALEA is finished only when the model is better supported by reproducible out-of-sample evidence, the data pipeline is temporally correct, and the full product works reliably. Passing unit tests, having many stages, or producing confident-looking percentages is not enough.
