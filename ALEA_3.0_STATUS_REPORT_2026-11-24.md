# ALEA 3.0 — Consolidated status report (24 Nov 2026)

This report supersedes every earlier status, progress, plan and session report in the repository root (they now carry a "superseded" banner). Every number below was produced in this session by the scripts named next to it, on the real data described in "Data". Nothing was copied from older reports.

**Bottom line:** ALEA 3.0 is **not released**. The frozen champion `alea-dc-v2.4.1` (Dixon–Coles MLE, fixed xi=0.0018, reg=1.0) stays. None of the 8 pre-registered challengers, temperature calibration, per-fold hyperparameter tuning or the dev candidate beat it with statistical support. The real-data Stage 9 pipeline now runs end to end for the first time, and live pre-kickoff forecasts are being recorded in a tamper-evident ledger.

There are **14 stages (0–13)**, not 18.

## Stage-by-stage status

| Stage | Scope | Status | Evidence / what is still missing |
|---|---|---|---|
| 0 | Reproducible checkout, frozen baseline | DONE | `sha256sum -c SHA256SUMS.txt` OK. v2.4.1 hash `4cfc6108…f022a` is unchanged. `tests/run_all.py` no longer reports false passes (see Fixes). |
| 1 | Data store, team identity, real feeds | DONE | 7 OpenFootball seasons 2019-20…2025-26: 2,660 matches, fingerprint `37afdac1…6f9b`. Three real-feed bugs are fixed and covered by regression tests. |
| 2 | Dixon–Coles core | DONE | `tests/test_stage2_parity.py` checks that exact 1X2/BTTS/O-U match the production model. |
| 3 | Elo / form features | EVALUATED, NOT ADOPTED | Elo and form were evaluated as probability models and as stack inputs on identical fixtures. None was accepted (table below). |
| 4 | xG | BLOCKED (data) | Timestamped historical xG exists only for the 110 matches of 2026-27 (football-data). It cannot be evaluated historically. |
| 5 | Players / injuries | BLOCKED (data) | There is no timestamped historical source. |
| 6 | Context factors | BLOCKED (data) | There is no timestamped historical source. |
| 7 | ML ensemble | NOT ADOPTED | Multinomial stackers (DC+Elo, DC+Elo+form) and an equal DC/Elo average were all rejected. No trained ML model exists. |
| 8 | Calibration | EVALUATED, NOT APPLIED | Temperature T=1.022 improves dev log-loss by only 4.8e-5. The new minimum gain gate (0.001) keeps it off. The rolling-temperature challenger was also rejected. |
| 9 | Walk-forward + holdout evaluation | DONE (first real run) | Weekly expanding window, holdout 2025-26, paired ISO-week block bootstrap. A prospective ledger is live. |
| 10 | Registry / promotion | CODE ONLY | Evidence-gated registry exists. Nothing was promoted because no challenger passed. There is no scheduler. |
| 11 | Prediction service | CODE ONLY | Traceable response and history store exist. No running API. |
| 12 | Reliability / security | DRILL PASSES, NOT DEPLOYED | `scripts/recovery_drill.py` was missing despite STATUS.md citing it. It now exists and passes 6/6 checks. Freshness gates are used by the forecast script. The secret scan passes. |
| 13 | Final acceptance | NOT COMPLETE | Release-gate items still open: deployed service and automation, and accumulated prospective evidence. |

## Data

- **Historical:** OpenFootball `football.json` (CC0), seasons 2019-20 to 2025-26, fetched by `scripts/fetch_openfootball.py`. Raw files and the SQLite store stay in `data/` (gitignored); only source manifests are uploaded by CI.
- **Current season:** football-data.co.uk `2627/E0.csv` (110 results through 23 Nov 2026). Its [disclaimer page](https://www.football-data.co.uk/disclaimer.php) states no licence, so it is read only from a local copy and never committed.
- **Fixtures:** OpenFootball 2026-27. Its results stop at 20 Sep 2026, so it is used for fixtures and cross-checking only.

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

## Tests and checks (this session)

| Check | Result |
|---|---|
| `python -m pytest -q` | 115 passed (82 at session start) |
| `python tests/run_all.py` | 36/36 files pass, with no false passes (see `TEST_RESULTS.txt`) |
| `python dev/tests/test_dev_repairs.py` | ALL DEV CHECKS PASSED |
| `python scripts/security_check.py` | no secrets found |
| `sha256sum -c SHA256SUMS.txt` | v2.3.1, v2.4.1, value engine v0.2.1 all OK |
| `python scripts/recovery_drill.py` | 6/6 checks pass |

New test files:

- `test_stage1_real_feed_regressions.py`
- `test_stage2_parity.py`
- `test_stage9_candidates.py`
- `test_stage9_compare_runs.py`
- `test_stage9_prospective_ledger.py`
- `test_stage9_prospective_forecast.py`
- `test_stage12_recovery_drill.py`

## What remains (in priority order)

1. **Accumulate prospective evidence.** Run the forecast script every matchweek. At about 150 settled forecasts, compare the champion and the DC/Elo average on the ledger.
2. **Choose a results feed with a clear licence**, or get permission from football-data. Then schedule the forecast script (Stage 10) and let it upload artifacts only.
3. **Deploy the prediction service (Stage 11)** behind the ledger, and run the recovery drill against the real store (Stage 12).
4. **Stages 4–6 need timestamped historical xG, lineup and injury data** before they can be evaluated.
5. **Stage 13 can close only after items 1–3.** Do not tag v3.0.0 before then.

## Caveat on the 2025-26 holdout

The 2025-26 holdout has now been looked at. It was used only to score fixed, pre-registered models, never to choose parameters. From here on, the prospective ledger is the only untouched test set.
