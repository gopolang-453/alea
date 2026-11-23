# Release notes — `alea-dc-dev` robustness candidate

**Status: proposed, NOT released.** Nothing has been merged, tagged or published. `alea_predictor_v2_4_1.py` remains the frozen baseline (SHA-256 unchanged, verified) and stays available for rollback and comparison. This file documents what the candidate is, what it is not, and what needs sign-off before anyone calls it a release.

## What changed vs v2.4.1

A diff of `dev/alea_predictor_dev.py` against the frozen baseline shows exactly four changes, nothing else:

1. **Refuses `reg = 0` when a team has scored or conceded no goals.** The unpenalised Poisson MLE is unbounded in that case (the likelihood keeps improving as that team's strength goes to −∞), and the optimiser previously stopped at a nonsense value instead of failing. Now it raises `ValueError` with the message naming the team.
2. **Refuses any fit where attack or defence strength exceeds 3 log-points** (~20× the league scoring rate), regardless of what caused it. Raises `RuntimeError`.
3. **`reg = 0` removed from `tune_params`'s candidate grid** (it can no longer be silently selected during tuning).
4. Two additional Manchester United name aliases ("man united", "manchester united").

Nothing else differs. No changes to the Dixon-Coles math itself, the score grid, the value engine, data cleaning, or cutoff enforcement.

## Why this is a robustness fix, not a proven accuracy improvement

On the 1,140-match evaluation set, the dev candidate's entire log-loss improvement over v2.4.1 (0.9868 vs 0.9964) comes from a single match — Burnley 2–0 Sunderland, 23 August 2025 — where v2.4.1 assigned the actual outcome a probability of ~2.7×10⁻⁷. The dev candidate's guard #1 above prevents that specific failure mode and assigns it 9.9% instead.

Excluding that one match, the dev candidate is marginally **worse** than v2.4.1 across the remaining 1,139 matches (mean log-loss +0.0016, well within noise). So: promote this candidate to stop a real, catastrophic failure mode — not because it makes better football predictions in general. Don't describe it to anyone as a performance upgrade.

## Regression testing performed

- `python tests/run_all.py` — 17/17 v2.4.1 test files pass (re-run and independently verified, not just reported).
- `python dev/tests/test_dev_repairs.py` — all checks pass, including:
  - `test_reg0_refuses_a_team_with_no_goals` — guard #1
  - **`test_extreme_team_strength_refused` (new, added during this review)** — guard #2. Constructs a small league where one team wins every match by the maximum plausible margin (15–0) and confirms the fit is refused with reg at 0.0001/0.001/0.01, and fits normally once reg is reasonable (0.1). Guard #2 had no prior test coverage.
  - `test_alias_and_save_load` — guard #3/#4, plus save/load round-trip and value-engine integration
  - `test_invalid_input_refused` — a team cannot play itself
  - `test_shin_and_value_arithmetic` — Shin de-vig sums to 1, value-engine EV arithmetic correct, staking stays off
- `tests/test_stage1_data_store.py` — pytest isn't installed and there's no network access in this environment to install it. Its 8 assertions were reimplemented with plain `assert`/`try-except` (same logic, same fixture file, no pytest) and run directly: 8/8 pass. This is a workaround, not a substitute for actually running the pytest file in an environment that has it.
- Frozen baseline file hash reconfirmed unchanged: `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`.

## What would need to happen before an actual release

1. Your explicit sign-off (nothing has been merged, tagged, or pushed).
2. Agreement that "robustness release" is the correct label — not "performance release."
3. Ideally, run `test_stage1_data_store.py` for real once pytest is installable (this doesn't block the dev candidate itself, since dev doesn't touch `stages/`).
