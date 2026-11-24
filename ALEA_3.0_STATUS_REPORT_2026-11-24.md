# ALEA 3.0 — Consolidated status report (24 Nov 2026, updated after the second pass)

> Superseded in part by `ALEA_3.0_FINAL_AUDIT_2026-11-24.md` (final audit: findings register, commit gate, pairing rules, odds removal). Where they differ, the final audit is current.

This report supersedes every earlier status, progress, plan and session report in the repository root (they now carry a "superseded" banner). Every number below was produced in this session by the scripts named next to it, on the real data described in "Data". Nothing was copied from older reports.

**Bottom line:** ALEA 3.0 is **not released**. The frozen champion `alea-dc-v2.4.1` (Dixon–Coles MLE, fixed xi=0.0018, reg=1.0) stays. None of the 8 pre-registered challengers, temperature calibration, per-fold hyperparameter tuning or the dev candidate beat it with statistical support. The real-data Stage 9 pipeline now runs end to end for the first time, and live pre-kickoff forecasts are being recorded in a tamper-evident ledger.

**Second pass (same day):** the following are now implemented and tested.

- Prospective settlement and evaluation, including postponed, cancelled, abandoned and rescheduled matches, conflicts, and duplicates.
- A licensed current-season results source: Wikipedia CC BY-SA 4.0, which matched football-data on 110/110 results.
- A scheduled forecast workflow with alerting, using a dedicated `prospective-ledger` data branch.
- The Stage 11 HTTP API and container.
- The Stage 12 drill against the real ledger and the real service (17/17).
- A champion-vs-closing-market comparison.

Operations, data licensing, evaluation rules and the maths are documented in `docs/`. The release checklist is `RELEASE_READINESS_CHECKLIST.md`.

There are **14 stages (0–13)**, not 18.

## Stage-by-stage status

| Stage | Scope | Status | Evidence / what is still missing |
|---|---|---|---|
| 0 | Reproducible checkout, frozen baseline | DONE | `sha256sum -c SHA256SUMS.txt` OK. v2.4.1 hash `4cfc6108…f022a` is unchanged. `tests/run_all.py` no longer reports false passes (see Fixes). |
| 1 | Data store, team identity, real feeds | DONE | 7 OpenFootball seasons 2019-20…2025-26: 2,660 matches, fingerprint `37afdac1…6f9b`. Three real-feed bugs are fixed and covered by regression tests. |
| 2 | Dixon–Coles core | DONE | `tests/test_stage2_parity.py` checks that exact 1X2/BTTS/O-U match the production model. |
| 3 | Elo / form features | EVALUATED, NOT ADOPTED | Elo and form were evaluated as probability models and as stack inputs on identical fixtures. None was accepted (table below). |
| 4 | xG | BLOCKED (data) | No source combines a licence for storage and training, continuous PL coverage and timestamps (StatsBomb open: non-commercial and partial; FBref: terms forbid ML; Understat: no licence). See `docs/DATA_SOURCES_AND_LICENSING.md`. |
| 5 | Players / injuries | BLOCKED (data) | There is no licensed source with availability timestamps. Lineups appear about 1 h before kickoff, which is incompatible with forecasts made ≥48 h ahead. |
| 6 | Context factors | BLOCKED (data) | Rest days could be derived from CC0 fixtures, but for PL games only, which would mismeasure rest. Not implemented. |
| 7 | ML ensemble | NOT ADOPTED | Multinomial stackers (DC+Elo, DC+Elo+form) and an equal DC/Elo average were all rejected. No trained ML model exists. |
| 8 | Calibration | EVALUATED, NOT APPLIED | Temperature T=1.022 improves dev log-loss by only 4.8e-5. The new minimum gain gate (0.001) keeps it off. The rolling-temperature challenger was also rejected. |
| 9 | Walk-forward + holdout evaluation | DONE (first real run) | Weekly expanding window, holdout 2025-26, paired ISO-week block bootstrap. A prospective ledger is live. |
| 10 | Registry / promotion / automation | IMPLEMENTED, CI-TESTED, SCHEDULE PENDING MERGE | `config/model_registry.json` (frozen champion with hash, 2 pre-registered prospective challengers, promotion rule ≥300 paired settled fixtures, never automatic). `.github/workflows/weekly-prospective-forecast.yml` runs Tue/Fri 06:00 UTC once on `main`. |
| 11 | Prediction service | IMPLEMENTED AND TESTED, NOT DEPLOYED | `stages/stage11/api.py` + `scripts/serve_api.py` + `Dockerfile`. 20 API tests, a container smoke test in CI, and a 503 on a foreign model, a hash mismatch or a corrupt ledger. No public host. |
| 12 | Reliability / security | EXERCISED ON THE REAL STORE AND SERVICE, NOT A PRODUCTION DEPLOYMENT | `scripts/recovery_drill.py --ledger` covers 17 checks: backup, restore, interrupted write, corruption, missing DB, tampered backup, history-loss refusal, duplicates after restore, service 200/503, secrets, failure logging and freshness. 17/17 pass on the real ledger. |
| 13 | Final acceptance | NOT COMPLETE | Open: public API deployment, the schedule live on `main`, ≥300 settled prospective forecasts (now 10 forecast, 0 settled), and Stages 4–6. |

## Data

- **Historical:** OpenFootball `football.json` (CC0), seasons 2019-20 to 2025-26, fetched by `scripts/fetch_openfootball.py`. Raw files and the SQLite store stay in `data/` (gitignored); only source manifests are uploaded by CI.
- **Current season (automated, second pass):** the Wikipedia article "2026–27 Premier League", under [CC BY-SA 4.0](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content).
  - It is read through the MediaWiki API, and the revision id is recorded per run.
  - Revision 1387424026 matched football-data.co.uk on 110/110 results.
- **football-data.co.uk:** its [terms](https://football-data.co.uk/contact.php) allow personal/academic use only (≤2 automated downloads a week). It is now only an optional local cross-check and is never committed.
- **Fixtures:** OpenFootball 2026-27 (CC0). Its results stop at 20 Sep 2026, and later dates are placeholder matchweek dates (±2 days), hence the 48 h minimum lead.
- **Full licensing findings:** `docs/DATA_SOURCES_AND_LICENSING.md`. It flags that the already-committed `results/predictions_*odds*.csv` files contain football-data Bet365 odds; removal is recommended.

## Fixes made in this session

1. **Stage 9 real-data workflow had never succeeded.** CI run 45056028252 died with `TypeError: ufunc 'isnan' not supported` because goals had object dtype. The fix is `_coerce_goals()`. The runner now also supports `--model v2.4.1|dev`, `--tune` (tuning inside each training window only), `--seasons`, and per-row xi/reg recording, and it validates season date windows.
2. **OpenFootball 2025-26 bare-list scores.** Results such as `"score": [0, 0]` were rejected. They are now read as full-time scores.
3. **66 misdated 2019-20 restart matches (leakage hazard).** They were listed as 2019-07-xx but played in 2020-07. The correction is narrow: only a date in the season's first calendar year that falls before 1 Aug, where moving it forward one year lands inside the season. Each correction is recorded in the manifest. Any other out-of-window date raises an error.
4. **Team identity.** "Sunderland AFC", "Hull City AFC" and the football-data short names (Hull, Coventry, Leeds, Nott'm Forest, …) now map to a single ID. The dev model rejected lowercase names; the runner now maps names through each model's own alias table.
5. **Calibration gate.** `fit_temperature` switched itself on for a 4.8e-5 gain. It now needs `min_improvement=0.001`.
6. **`tests/run_all.py` false passes.** Pytest-style files were executed as plain scripts, ran nothing, and printed PASS. Two of them actually failed with `No module named 'stages'`. The runner now sets `PYTHONPATH` and runs those files through pytest.
7. **Missing `scripts/recovery_drill.py`** (cited by Stage 12) has been written and tested.
8. **CI:** the Stage 9 workflow now uses 7 seasons and the 2025-26 holdout, runs the challenger evaluation and the recovery drill, and triggers on the new files.

## Stage 9 results — champion v2.4.1 (fixed xi/reg, weekly refit)

Source: `results/stage9_mle/report.json` (`scripts/run_stage9_mle_backtest.py --holdout-season 2025-26 --step-days 7`).

| Period | n | Log-loss | Brier | RPS | Accuracy | Δ log-loss vs training-rate baseline (95% CI) |
|---|---|---|---|---|---|---|
| Development 2020-21…2024-25 | 1,900 | 0.9796 | 0.5821 | 0.2035 | 0.539 | −0.0884 [−0.1051, −0.0712] |
| Holdout 2025-26 | 380 | 1.0274 | 0.6164 | 0.2088 | 0.474 | −0.0574 [−0.0917, −0.0218] |

The model clearly beats the naive base rate in both periods. The 2025-26 season was harder (log-loss 1.027 vs 0.980). For context, the earlier audit measured Bet365 closing odds at 0.9595 on 2023-26, so the model remains well behind the market. Staking stays off.

## Challengers (pre-registered, identical fixtures)

Source: `results/stage9_candidates/report.json` (`scripts/run_stage9_candidate_evaluation.py`). The protocol, Elo settings and acceptance rule are written into the script and the report before any scoring. A challenger is accepted only if all three hold: the holdout Δ log-loss CI95 upper bound is < 0, holdout Δ Brier ≤ 0, and development Δ log-loss < 0. The first 380 matches are an Elo burn-in, so development is scored on the 1,520 rows that every model covers.

| Candidate | Dev log-loss (n=1,520) | Holdout log-loss | Holdout Δ vs champion (95% CI) | Decision |
|---|---|---|---|---|
| Champion DC v2.4.1 | 0.9688 | 1.0274 | — | stays |
| Training-rate baseline | 1.0652 | 1.0848 | +0.0574 [+0.0204, +0.0928] | REJECT |
| Elo ordered logit | 0.9693 | 1.0279 | +0.0005 [−0.0153, +0.0166] | REJECT |
| Form ordered logit | 1.0257 | 1.0679 | +0.0405 [+0.0114, +0.0722] | REJECT |
| DC re-stack (control) | 0.9780 | 1.0281 | +0.0007 [−0.0069, +0.0086] | REJECT |
| DC + Elo stack | 0.9727 | 1.0244 | −0.0030 [−0.0116, +0.0056] | REJECT |
| DC + Elo + form stack | 0.9738 | 1.0250 | −0.0024 [−0.0109, +0.0064] | REJECT |
| DC rolling temperature | 0.9702 | 1.0272 | −0.0001 [−0.0009, +0.0007] | REJECT |
| DC/Elo equal average | 0.9659 | 1.0243 | −0.0030 [−0.0108, +0.0048] | REJECT |

The equal DC/Elo average is the only challenger better in both periods. Its gain is about 0.003 log-loss, and the CI includes zero. It is worth re-testing on prospective data, but it cannot be promoted now.

## Hyperparameter tuning and the dev candidate (28-day folds, paired)

Sources: `results/stage9_tuning_vs_fixed/`, `results/stage9_dev_vs_v241/`, `results/stage9_dev_vs_v241_fixed/` (`scripts/compare_stage9_runs.py`). The comparison refuses to run unless both runs cover identical fixtures and cutoffs.

| Comparison | Dev Δ log-loss (95% CI) | Holdout Δ log-loss (95% CI) | Verdict |
|---|---|---|---|
| v2.4.1 tuned per fold − v2.4.1 fixed | +0.0113 [+0.0014, +0.0257] | +0.0033 [−0.0036, +0.0101] | Tuning is significantly **worse** |
| dev tuned − v2.4.1 tuned | −0.0077 [−0.0206, −0.0004] | −0.0002 [−0.0047, +0.0039] | Dev guards help only when tuning is on |
| dev tuned − v2.4.1 fixed | +0.0036 [−0.0009, +0.0081] | +0.0032 [−0.0032, +0.0087] | No gain over the champion |

Root cause: v2.4.1's own `tune_params` chooses reg=0 for 794 of 1,900 development predictions. That produces degenerate probabilities, e.g. Everton v Nottingham Forest (20 Aug 2022) was given p_away = 3.4×10⁻⁶. This confirms the earlier verdict: the dev candidate is a robustness fix (it removes reg=0), not an accuracy gain. Keep reg fixed at 1.0.

## Prospective forecasts (live)

`scripts/run_prospective_forecast.py` fits the champion on all results available before the run time. It then records forecasts in `results/prospective/ledger.sqlite` (append-only, pre-kickoff only, never overwritten). It blocks if any gate fails:

- **Completeness:** every past fixture has a result. 110/110 passed.
- **Cross-feed agreement:** the 50 results in both feeds agree exactly. 0 disagreements.
- **Stage 12 freshness:** the latest result was 16.6 h old (limit 240 h).

First run (24 Nov 2026 14:36 UTC): 10 forecasts for 28 Nov 2026, training on 2,770 matches, ledger fingerprint `cf486e7d…381b8`. A second run was idempotent: 0 added, 10 kept. OpenFootball gives 15:00 for all ten; if TV picks change kickoffs, the ledger still holds because the forecasts were made four days early. Re-run the script after each matchweek to settle outcomes and add the next fixtures.

**Second pass.** The pipeline now does the following:

- **Results and settlement:** it fetches Wikipedia results and settles finished fixtures, recording every source observation. Disagreement creates a conflict that excludes the fixture until an operator correction.
- **Fixture events:** it handles postponed, rescheduled, cancelled, abandoned and void fixtures through events.
- **Challengers:** it records the 2 registered challengers for the same fixtures, using the recorded champion probabilities.
- **Outputs:** it writes `report.md` and `evaluation.json` (settled and outstanding forecasts, metrics with CIs, challenger comparison, data-quality issues).

A local run on a copy of the ledger with a live Wikipedia fetch (24 Nov 2026 15:32 UTC) gave status ok:

- 0 new champion forecasts (all 10 already recorded);
- 20 challenger rows recorded, with the champion fingerprint unchanged;
- a second run added nothing.

The live ledger now lives on the `prospective-ledger` branch, seeded byte-identically; the scheduled workflow is its only writer.

The first CI run of the workflow (run 45432121912) did the same on the live ledger:

- status ok;
- 0 new and 10 kept;
- 20 challenger rows recorded;
- drill passed;
- API smoke test passed;
- committed by github-actions to the data branch. Rules: `docs/PROSPECTIVE_EVALUATION.md`.

## Champion vs closing market (second pass, Task 7)

`scripts/compare_vs_market.py` writes aggregates only to `results/stage9_market/`. It pairs the frozen champion's leakage-free walk-forward forecasts with Bet365 closing Shin probabilities on 1,140 identical fixtures (0 unmatched). Differences are champion − market, with ISO-week block-bootstrap 95% CIs.

| Slice | n | LL diff [95% CI] | Brier diff [95% CI] |
|---|---:|---:|---:|
| All 2023-24…2025-26 | 1,140 | +0.0222 [+0.0122, +0.0317] | +0.0150 [+0.0083, +0.0220] |
| 2023-24 | 380 | +0.0299 [+0.0101, +0.0483] | +0.0213 [+0.0083, +0.0331] |
| 2024-25 | 380 | +0.0229 [+0.0063, +0.0390] | +0.0163 [+0.0034, +0.0278] |
| 2025-26 | 380 | +0.0137 [−0.0025, +0.0315] | +0.0075 [−0.0038, +0.0193] |
| Market favourite < 0.50 | 474 | +0.0252 [+0.0095, +0.0405] | +0.0181 [+0.0066, +0.0294] |
| Market favourite 0.50–0.65 | 408 | +0.0229 [+0.0082, +0.0393] | +0.0158 [+0.0051, +0.0269] |
| Market favourite ≥ 0.65 | 258 | +0.0154 [−0.0066, +0.0371] | +0.0081 [−0.0065, +0.0221] |

- **Gap to the market:** the market is better in every slice, and the gap is significant overall.
- **Calibration:** expected calibration error is 0.0176 for the champion and 0.0083 for the market.
- **Other evaluation findings (focus areas):**
  - **DC/Elo equal average:** better than the champion in 4 of 5 seasons (2021-22 is the exception). The holdout gain is −0.0030 [−0.0108, +0.0048] (n=380), which is too small and uncertain to promote, so it is registered as a prospective challenger.
  - **Dev model:** its guards (no reg=0 for goalless teams; strength cap of 3 log-points) target fits the fixed champion (reg=1.0) does not use. Tuned dev vs fixed champion: dev Δ LL +0.0036 [−0.0009, +0.0081], n=1,900, which shows no gain. It is a robustness fix only and is not registered as a challenger.
  - **Experiments that did not help:** temperature calibration, per-fold tuning, the stacks and rolling temperature all failed (tables above).

## Tests and checks (this session)

| Check | Result |
|---|---|
| `python -m pytest -q` | 115 passed (82 at session start); **194 passed** after the second pass (local 15m55s; CI run 45432120603) |
| `python tests/run_all.py` | 36/36 files pass, with no false passes (see `TEST_RESULTS.txt`); 43/43 after the second pass |
| `python dev/tests/test_dev_repairs.py` | ALL DEV CHECKS PASSED |
| `python scripts/security_check.py` | no secrets found |
| `sha256sum -c SHA256SUMS.txt` | v2.3.1, v2.4.1, value engine v0.2.1 all OK |
| `python scripts/recovery_drill.py` | 6/6 checks pass |
| `python scripts/recovery_drill.py --ledger results/prospective/ledger.sqlite` (second pass) | 17/17 checks pass. The real ledger is byte-identical afterwards |
| Second-pass test files | `test_prospective_pipeline.py`, `test_prospective_ledger_v2.py`, `test_live_sources.py`, `test_stage11_api.py`, `test_stage12_ledger_ops.py`, `test_ledger_admin.py`, `test_compare_vs_market.py` |

New test files:

- `test_stage1_real_feed_regressions.py`
- `test_stage2_parity.py`
- `test_stage9_candidates.py`
- `test_stage9_compare_runs.py`
- `test_stage9_prospective_ledger.py`
- `test_stage9_prospective_forecast.py`
- `test_stage12_recovery_drill.py`

## What remains (in priority order)

1. **Merge to `main`, with the owner's permission,** so the Tue/Fri schedule fires. Until then, the workflow runs only when its file changes on a `repair/**` branch.
2. **Accumulate prospective evidence.** The promotion rule needs at least 300 paired settled fixtures, about 30 matchweeks. Do not compare earlier except as a monitoring check.
3. **Deploy the API publicly** (container and instructions in `docs/OPERATIONS.md`), then re-run the drill against the deployed instance.
4. **Decide on the committed odds files** (`results/predictions_*odds*.csv`, football-data terms).
5. **Stages 4–6:** acquire a licensed, timestamped source first.
6. **Stage 13 closes only when every row of `RELEASE_READINESS_CHECKLIST.md` is satisfied.** Do not tag v3.0.0 before then.

## Caveat on the 2025-26 holdout

The 2025-26 holdout has now been looked at. It was used only to score fixed, pre-registered models, never to choose parameters. From here on, the prospective ledger is the only untouched test set.
