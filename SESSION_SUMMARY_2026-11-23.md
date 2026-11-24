> **Superseded (24 Nov 2026):** see [ALEA_3.0_STATUS_REPORT_2026-11-24.md](ALEA_3.0_STATUS_REPORT_2026-11-24.md) for current, re-measured status. Kept for history only.

# Session summary — 2026-11-23

What this session actually did, in order. Nothing below was fabricated — every number came from either re-running the existing test suite or recomputing metrics directly from the raw rows in `results/`.

## 1. Repository audit
- Corrected an earlier (wrong) handover document that described a broken `stages/stage8/calibration.py` and a Stage 1–13 production pipeline. That file and that structure don't exist in this repository — don't act on documentation describing them.
- Confirmed actual structure: `alea_predictor_v2_4_1.py` (frozen baseline), `dev/alea_predictor_dev.py` (robustness candidate), `alea_value_engine_v0_2_1.py`, `frozen/alea_predictor_v2_3_1.py`, and an incomplete `stages/` feature-contract scaffold that is not imported by either released predictor.

## 2. Test verification (re-run, not just reported)
- `tests/run_all.py`: 17/17 test files pass.
- `dev/tests/test_dev_repairs.py`: all pass, including a new test added this session (`test_extreme_team_strength_refused`) covering the 3-log-point team-strength sanity guard, which previously had zero test coverage.
- `tests/test_stage1_data_store.py` needs `pytest`, unavailable with no network access in this environment. Its 8 assertions were reimplemented without pytest and run directly: 8/8 pass. This is a workaround — the actual pytest file should still be run in an environment that has pytest, for a true result.
- Frozen baseline file hash reconfirmed unchanged throughout: `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`.

## 3. Dev candidate vs frozen baseline — diff and verdict
Four changes only: refuses `reg=0` when a team has zero goals scored/conceded (unbounded MLE), refuses any fit with a team strength beyond 3 log-points, drops `reg=0` from the tuning grid, adds two Manchester United aliases. See `RELEASE_NOTES_DEV_CANDIDATE.md`.

**Verdict: robustness fix, not a demonstrated accuracy improvement.** Its entire log-loss advantage over v2.4.1 on the 1,140-match evaluation set comes from one match (Burnley 2–0 Sunderland, 23 Aug 2025, where v2.4.1 assigned the true outcome ~2.7×10⁻⁷ probability). Excluding that match, dev is marginally worse than v2.4.1 (+0.0016 log-loss, within noise).

## 4. Benchmark reproduction (independent, from raw data)
Recomputed log-loss/Brier/RPS/accuracy directly from `results/predictions_closing_odds.csv` and `results/predictions_closing_dev.csv` — not from the summary JSON. Confirmed: v2.4.1 0.9964, dev 0.9868, Shin-devigged Bet365 closing 0.9595 log-loss. Matches the README's previously-reported 0.996/0.960. Data integrity checked: no duplicates, no missing/invalid odds, no leakage (odds-info date never after match date), results consistent with recorded goals.

**Not yet done: refitting from scratch.** The `results/` files only contain the 1,140 evaluation matches, not the earlier training-period rows each fold used. Refitting and testing real changes (different `reg`/`xi`, Elo, calibration, training-window length) needs that earlier history — see `DATA_CHECKLIST_AND_EXPERIMENT_PLAN.md` for exactly which files.

## 5. Deliverables added this session
- `README.md` — updated with the verified benchmark table, per-season breakdown, explicit robustness-vs-accuracy framing, draw-calibration note, and a limitations section.
- `RELEASE_NOTES_DEV_CANDIDATE.md` — new.
- `DATA_CHECKLIST_AND_EXPERIMENT_PLAN.md` — new.
- `dev/tests/test_dev_repairs.py` — one test added (team-strength sanity check coverage).

## Status: nothing released
No merge, tag, or publish has happened. The frozen baseline is untouched. The dev candidate remains a proposal pending your sign-off, as `RELEASE_NOTES_DEV_CANDIDATE.md` states explicitly.

## Still blocked
Phase 5's five experiments (regularisation/time-decay search, training-window length, team-specific home advantage, Elo, calibration) cannot start until the pre-11-Aug-2023 historical EPL data is supplied. See the checklist doc for the exact files.
