# ALEA 3.0 — Engineering Repair Plan and Acceptance Gates

**Prepared:** 18 November 2026  
**Repository:** `gopolang-453/alea`  
**Status:** Remediation plan; not a claim that the release is complete.

## 1. Executive decision

Do not release ALEA 3.0, replace the frozen v2.4.1 predictor, enable staking, or describe the model as production-ready yet.

The immediate priority is to make the repository reproducible and internally consistent, then evaluate the actual production Dixon–Coles implementation and candidate features on strictly out-of-sample data. A feature, API, ML model, interface, or deployment is not a release requirement merely because it appears in the roadmap: it is accepted only when it has a working implementation, tests, operational evidence, and documented limitations.

## 2. Repository audit findings that must be resolved first

The repository tree inspected on 18 November 2026 contains the root predictor, a development predictor, the Stage 1 in-memory data store, Stage 2 mathematics, feature modules for Stages 4–7, one Stage 9 test, and the legacy predictor tests. It does **not** contain the Stage 9 data directory or the persistent-store module referenced by the Stage 9 test.

Specific inconsistencies:

1. `stages/stage9/tests/test_stage9_1_real_data.py` imports `stages/alea_stage1/persistent_store.py` and expects `stages/data/epl/E0_1920.csv` through `E0_2324.csv`. Neither the referenced package nor those data files appear in the inspected repository tree. The test therefore cannot substantiate the reported import PASS as currently committed.
2. The actual Stage 1 module found is `stages/stage1/data_store.py`. It is an in-memory `DataStore`, not the persistent SQLite `PersistentDataStore` referenced by the test. Its `ingest_results_frame` also appends records without its own duplicate/idempotency guard.
3. The current production predictor's API fetch function deliberately raises `NotImplementedError`; its comments describe a placeholder endpoint and response schema. No live API integration should be called complete.
4. `DEV_REPORT.md` and `FULL_AUDIT.md` document a repaired development candidate (`alea-dc-dev`) while explicitly preserving v2.4.1. The known `reg=0` unbounded-fit defect is therefore not repaired in the frozen production file. Do not silently replace the reference model.
5. `ALEA_3.0_COMPLETE_STATUS_REPORT.md` reports a 1,900-row / 1,600-prediction Stage 9 run, while the committed test and repository tree do not currently provide the referenced data and persistent store. Treat those numbers as **reported, not independently reproducible from this checkout**, until the artifacts and exact commands are committed.
6. Several status reports claim Stage 8 and Stages 10–12 work, but the inspected tree does not contain the corresponding complete stage implementation paths. Verify every reported artifact against the actual tree and test runner before retaining those status labels.
7. The Stage 2 score grid returns a truncated grid plus a tail probability. Downstream 1X2/BTTS calculations currently normalize by the grid mass, so their semantics are conditional on the chosen grid. Reports must disclose this, and tests must quantify truncation error or use a sufficiently large/adaptive grid.

These are repository-integrity and evidence problems, not proof that every underlying idea or calculation is wrong.

## 3. Non-negotiable engineering rules

- Preserve `alea_predictor_v2_4_1.py` and its recorded SHA-256 as the frozen reference until a separately versioned candidate passes acceptance.
- Do not edit files under `frozen/` or overwrite historical result artifacts.
- Every experiment gets a unique run ID, commit SHA, data fingerprint, configuration, cutoff policy, code version, and output artifact.
- Train only on information available before the prediction cutoff. Split by match date, not arbitrary row order; all fixtures on a date stay in the same fold unless trustworthy kickoff/completion timestamps support a finer policy.
- Never use closing odds, full-time stats, post-match xG, final lineups, or injuries published after the decision time as prediction inputs.
- Hyperparameter selection and calibration must use training/validation history only. The final holdout is opened once after the model and protocol are frozen.
- Compare probability forecasts using log loss, multiclass Brier score, RPS, calibration/reliability, and uncertainty intervals. Accuracy is supplementary, not the selection metric.
- Compare against at least: historical/base-rate forecast, the production Dixon–Coles model, and time-aligned de-vigged bookmaker probabilities where the odds timestamp is credible.
- No model is promoted because it wins one metric on one sample. Report paired per-match score differences, confidence intervals, season-by-season results, and sample sizes.
- Do not force LightGBM/XGBoost into the system. Use them only if a fair chronological experiment demonstrates robust incremental value.
- Betting/value/staking remains disabled unless a separate, pre-registered evaluation supports positive expected value after margin, limits, and realistic execution assumptions.

## 4. Remediation sequence

### Phase A — Make the checkout reproducible (blocking)

**A1. Establish the actual repository layout**
- Record the default branch, commit SHA, file tree, Python version, and installed dependencies.
- Make the README the single entry point with exact setup and test commands.
- Remove stale status claims or label them as historical/unverified until artifacts exist.

**A2. Repair the Stage 9.1 test/data contract**
- Choose one canonical Stage 1 interface. Prefer the existing `stages/stage1/data_store.py` only if it is extended with persistent storage and idempotent ingestion; otherwise implement the persistent store as a real, tested module and update imports consistently.
- Commit a small synthetic CSV fixture for tests. Keep large historical datasets as reproducibly downloadable inputs or documented user-provided files; record source, retrieval date, URL, license/attribution, byte size, and SHA-256.
- Parse football-data CSV with UTF-8/BOM handling, date parsing, required-column checks, numeric score validation, team canonicalization, duplicate fixture detection, and explicit rejection/quarantine of malformed rows.
- Use a stable fixture key that includes competition/season, date, home team, and away team. Detect conflicting duplicate results rather than silently overwriting.
- Make imports transactional and idempotent. Re-importing identical files must add zero records; changed source rows must be detected and handled by an explicit correction policy.
- Do not invent exact result availability times from a date-only CSV. For conservative historical result snapshots, make a documented policy (e.g. result becomes usable from the next calendar day in the competition timezone) and test it. If kickoff/completion timestamps are available, use them explicitly.

**A2 PASS:** clean install succeeds; synthetic import succeeds; duplicate import adds zero; conflicting duplicate is rejected or audited; database closes/reopens with identical fingerprint; malformed and BOM files are handled; missing data fails loudly; no undocumented 1,900-match claim remains.

**A3. Make all tests discoverable**
- Add one canonical test command that runs Stage 1–13 tests and exits non-zero on any failure.
- Ensure tests import modules using package paths, not stale paths or working-directory assumptions.
- Add CI (e.g. GitHub Actions) to run the suite on each push and pull request.
- Keep slow historical backtests separate from fast unit tests, but expose a single documented command for the full validation suite.

**A3 PASS:** a clean checkout can run the documented unit suite; CI reports the same result; no test is skipped silently.

### Phase B — Verify the real Dixon–Coles predictor (blocking)

**B1. Reproduce the current reference**
- Run the existing v2.4.1 suite unchanged and preserve its log.
- Verify the frozen file hash equals the documented hash.
- Reproduce a known single-match prediction from a saved fixture and verify score-grid probabilities, 1X2, BTTS, totals, and serialization round-trip.

**B2. Resolve the zero-strength/unbounded MLE defect safely**
- Keep the frozen v2.4.1 unchanged.
- Treat `alea_predictor_dev.py` as a candidate. Review the regularization objective, constraints, convergence status, and team-strength bounds.
- Test zero-goal/zero-conceded teams, promoted/new teams, tiny samples, extreme scores, all-draw samples, optimizer failure, and non-finite parameters.
- Reject a fit if the optimizer did not converge or if parameters/probabilities are invalid; never quietly return a broken model.
- Verify that the regularization penalty is scaled consistently with sample size and time weights, and that the chosen regularization is tuned only inside each training window.

**B2 PASS:** pathological samples cannot create extreme finite-looking probabilities; every accepted fit reports convergence and valid parameters; reference file hash remains unchanged.

**B3. Run production-model walk-forward**
- Use the exact production fit and prediction functions, not the fast rates proxy.
- Use expanding chronological windows with date-grouped test blocks. Start with a predeclared minimum history and step size; report every fold, failed fold, skipped fixture, and unseen-team prior.
- Tune `xi` and regularization only within each fold's training window. Add an inner chronological validation split if tuning is used.
- Store one prediction row per fixture with cutoff, training range, model version, parameters, probabilities, actual outcome, and run/data hashes.
- Repeat the run from a clean environment and verify identical outputs within a defined numeric tolerance.

**B3 PASS:** zero cutoff violations; no silently skipped folds; all predictions valid and traceable; reproducible run; full per-season metrics and confidence intervals generated.

### Phase C — Establish a defensible benchmark and candidate model

**C1. Benchmark protocol**
- Evaluate the same fixtures for all comparators.
- Market odds may be a benchmark only when the odds timestamp is known to precede the prediction cutoff. Do not compare a model's early forecast with closing odds as if the closing price had been available earlier.
- Convert odds to fair probabilities with a documented method (Shin and proportional sensitivity check); reject incomplete or invalid markets.
- Calculate log loss, Brier, RPS, accuracy, calibration bins, and paired score differences. Include per-season and overall results.
- Use block/bootstrap resampling by match date or matchweek to account for temporal dependence; state the interval method and seed.

**C1 PASS:** benchmark rows align exactly by fixture and timestamp; no future odds; every metric can be regenerated from saved predictions.

**C2. Test Elo correctly**
- Do not use the previous fixed 0.25 draw probability as a final Elo 1X2 conversion.
- Estimate a draw-aware probability mapping from historical training-only data, or combine Elo as a feature in a model whose probabilities are trained on earlier out-of-sample predictions.
- Tune Elo K-factor, home advantage, initial ratings, and promoted-team priors inside training data only.
- Compare baseline DC, Elo-only, and DC+Elo on identical folds.

**C2 PASS:** Elo's incremental gain survives paired uncertainty analysis and does not depend on a single season or crude draw assumption. If not, retain it as experimental.

**C3. Combine features one at a time**
- Add recent form, then xG, then player availability, then context; evaluate each independently and incrementally.
- Each feature must have a source, timestamp/availability definition, missingness policy, coverage report, and leakage test.
- For historical xG/injury/lineup data, do not fabricate backfilled timestamps. If publication times are unavailable, exclude the feature from historical prediction evaluation or clearly restrict the claim.
- Test feature ablation and missing-data fallback. Keep a feature only if it improves the predeclared primary metric on later unseen matches and does not materially damage calibration/other metrics.
- If no trustworthy source exists, mark the feature NOT EVALUATED, not PASS.

**C3 PASS:** a documented decision (keep/reject/experimental) for each feature with identical-fixture evidence and coverage details.

**C4. Final combined model and untouched holdout**
- Freeze the model, features, tuning range, calibration method, and evaluation protocol before opening the final chronological holdout.
- Compare against DC and the time-aligned market benchmark.
- Publish the holdout metrics once. Do not retune after seeing them; a changed model requires a new future holdout.

**C4 PASS:** all holdout results and uncertainty intervals are published; no feature/model selection used holdout outcomes.

### Phase D — Calibration and probability integrity

- Generate out-of-sample predictions first, then fit calibration only on a separate chronological calibration segment.
- Compare uncalibrated probabilities with temperature scaling and, if sample size supports it, alternatives such as multinomial logistic calibration. Avoid isotonic calibration on small samples.
- Keep the final holdout untouched by calibration fitting.
- Evaluate log loss, Brier, RPS and reliability diagrams; calibration is not judged by one metric alone.
- Ensure score-grid tail mass is reported. Either increase/adapt the grid until tail mass is below a declared tolerance or calculate tail-aware 1X2 totals. Do not silently renormalize a materially truncated grid.
- Validate every probability is finite, in [0,1], and sums to one within tolerance.

**PASS:** calibration improves or preserves out-of-sample probability quality and reliability without holdout leakage; tail truncation is bounded and disclosed.

### Phase E — Automation (only after offline model is accepted)

- Build independent, retryable fetchers for fixtures and results using a documented provider/schema; validate status codes, schema, timestamps, rate limits, and source freshness.
- Store raw source responses and normalized records separately; retain provenance and source hashes.
- Make updates idempotent; handle postponements, cancellations, score corrections, promoted teams, renamed teams, and API outages.
- Schedule ingestion and prediction only after data validation passes.
- Train candidate models in an isolated job. Promote only if the candidate passes the same locked evaluation gates against the champion; otherwise retain champion.
- Add atomic model writes, backups, rollback, run logs, health checks, and alerting.
- Do not leave placeholder API endpoints or `NotImplementedError` functions labelled production-ready.

**PASS:** simulated outage, malformed response, rate limit, duplicate run, corrected score, failed fit, failed promotion, and rollback tests all pass; no stale or invalid model is served.

### Phase F — Interface, security, reliability, release

- Expose predictions with probabilities, kickoff/cutoff time, model version, data freshness, and missing/estimated feature flags.
- Explanations must identify actual model inputs; never invent injuries, lineups, xG, or reasons.
- Persist immutable prediction records so old outputs can be reproduced after model updates.
- Keep API keys out of source and logs; scan the full repository and git history where possible. Rotate any exposed secret.
- Test corrupted model files, interrupted writes, database backup/restore, dependency installation, and fresh-machine startup.
- Publish known limitations and model-vs-market performance honestly.
- Tag `v3.0.0` only after all release gates are green and the holdout report is signed off.

**PASS:** a clean installation, documented runbook, functioning interface, monitoring/recovery evidence, no secrets, reproducible model artifacts, and completed Stage 13 checklist.

## 5. Recommended order of execution

1. Fix the repository/test/data mismatch (Phase A).
2. Reproduce v2.4.1 and verify the development candidate (B1–B2).
3. Run the actual production Dixon–Coles walk-forward (B3).
4. Rebuild the benchmark and draw-aware Elo comparison (C1–C2).
5. Evaluate feature sources one by one (C3).
6. Freeze and test the combined model on an untouched holdout (C4).
7. Calibrate only from out-of-sample calibration predictions (D).
8. Build live automation (E).
9. Finish interface, security, reliability, and release acceptance (F).

Do not jump to automation or interface polish while the model's offline evaluation is not trustworthy.

## 6. Evidence required in every status report

Every PASS must link to:
- exact commit SHA and file paths;
- exact command and environment;
- test output / CI run;
- data source, date range, row count, fingerprint, and availability-time policy;
- model configuration and training cutoffs;
- prediction artifact and metrics;
- failed/skipped fold counts;
- confidence intervals and per-season breakdown.

Use only these labels: **PASS** (reproduced), **PARTIAL** (implementation exists but acceptance incomplete), **NOT EVALUATED** (required data/evidence unavailable), **FAIL** (test or gate failed), **BLOCKED** (dependency missing). Do not use "complete" for scaffolding alone.

## 7. Current status after this audit

- Stage 1 persistence/idempotency: **BLOCKED / inconsistent** in the inspected checkout.
- Stage 2 core formula tests: **PARTIAL** pending tail-mass semantics review.
- Production DC walk-forward: **NOT VERIFIED** by the committed Stage 9 artifacts.
- Development regularization repair: **candidate documented; requires reproducible checkout tests**.
- Elo improvement: **DIRECTIONAL ONLY**; fixed-draw conversion is not sufficient for acceptance.
- xG / injuries / lineups / context: **NOT EVALUATED** on reliable historical availability-timestamped data.
- Live API / scheduler: **BLOCKED**; current predictor fetch function is a placeholder.
- Stage 13 / v3.0.0: **NOT COMPLETE**.

This document is a repair specification. It does not itself implement or prove the listed engineering work.
