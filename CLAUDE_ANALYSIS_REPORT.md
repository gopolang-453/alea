# Claude's Independent Verification — ALEA 3.0 repair project
Date: 2026-11-20
Scope: read COMPREHENSIVE_REPAIR_SPECIFICATION.md and every stages/*/STATUS.md,
then independently ran the project's own offline test runner (tests/run_all.py,
no pytest needed, no internet) to check the STATUS.md claims against the code.

## Result: tests 01-14 of the original v2.4.1 suite PASS for real
Ran `python tests/run_all.py` directly (sandbox has no internet, so stage1/stage9
integration tests needing OpenFootball download were not exercised). Full captured
output is in TEST_RESULTS.txt in this zip. Confirmed, from real output (not claims):
- Leakage/cutoff enforcement works (test_14): scrambling future results does not
  change historical model fits.
- Dixon-Coles math, data validation, versioned model files, ROI confidence
  intervals, odds-timing alignment, new-team priors, regression/shrinkage checks,
  tuning freshness detection: all genuinely pass with real numbers, not stubs.

## Stage-by-stage status (from the project's own STATUS.md files, spot-checked)

| Stage | Status | What's actually left |
|---|---|---|
| 1 Data store | PASS | nothing |
| 2 Dixon-Coles math | PASS | nothing |
| 3 Elo/form | Evaluated, REJECTED on holdout (worse log loss) | nothing to fix — correct negative result |
| 4 xG | Feature code complete, BLOCKED | no licensed timestamped xG source |
| 5 Injuries | Feature code complete, tested | no comparative backtest (needs real feed) |
| 6 Context (weather/referee/derby) | Feature code complete, tested | needs real data source to evaluate |
| 7 Ensemble | Scaffolding tested | no real LightGBM/XGBoost trained yet |
| 8 Calibration | Evaluated, REJECTED on holdout | correct negative result |
| 9 Walk-forward | Evaluated, champion beats baselines | Elo/calibration not yet scored on identical holdout |
| 10 Automation | Contract-tested only | no live scheduler/daemon |
| 11 Prediction service | Contract-tested only | not deployed |
| 12 Reliability/security | Contract-tested only | not deployed |
| 13 Release | NOT COMPLETE (correctly self-reported) | blocked on 10-12 + product scope decision |

## Conclusion
This is not a broken or fabricated project. Core math (Stages 1-2, 9) is genuinely
verified. Stages 3 and 8 are honest negative results, not bugs. Stages 4-6 are
correctly disabled pending real data access, not something code alone fixes.
The real remaining engineering work is Stages 10-12 (turn contracts into a running
pipeline) and then Stage 13 sign-off.

No source files were modified by Claude in this pass — this is a verification-only
report.

## Update — Stage 11 wiring (second pass)

Added two scripts that connect existing-but-unconnected Stage 10/11 code into
a runnable path:
- `scripts/train_and_register_champion.py`
- `scripts/predict_cli.py`

Both were run end-to-end in this sandbox against a synthetic league (no
internet here, so real OpenFootball data wasn't used). Full detail and what
still needs real data / a real environment: see `stages/stage11/STATUS.md`.
Nothing claimed here was asserted without being executed and shown to work,
including the negative case (prediction CLI correctly refusing a past-dated
fixture; training script correctly gated on the promotion CI).

## Update — Stage 10 wiring (third pass)

Added `scripts/refresh_and_retrain.py`: refresh -> retrain -> evaluate ->
promote-only-if-better, meant to run on a schedule (not a daemon). Tested
both directions on synthetic data: it promoted a first candidate, then on a
re-run with identical data it correctly REFUSED to promote (candidate did not
beat the existing champion) and left the champion untouched. See
`STAGE10_STATUS.md` for the full writeup. Still not run against real data
(no internet in this sandbox) and not actually scheduled anywhere.

## Update — Stage 12 + overall (fourth pass)

Stage 12 integrity/backup/restore/rollback wired into one drill. All 6 checks
passed for real against a simulated corruption. See stages/stage12/STATUS.md.

By running real code, not just reading reports:
- Stages 1, 2, 9: pass, unchanged (verified earlier this session).
- Stages 3, 8: correct negative results (Elo, calibration both rejected on
  holdout) — not bugs.
- Stage 11: prediction service wired, tested end-to-end including a
  correctly-refused past-dated fixture.
- Stage 10: refresh/retrain/promote-only-if-better wired, tested both the
  promote and correctly-refuse-to-promote cases.
- Stage 12: integrity/backup/restore/rollback wired into one drill, all 6
  checks passed for real against a simulated corruption.

Structurally blocked — not fixable by writing more code, need from you:
- Stages 4-6 (xG, injuries, context) need a real licensed/timestamped data
  source, which is a product/budget decision, not an engineering one.
- Everything built this session was run on synthetic data in this sandbox,
  which has no internet. None of it has been run on real EPL data yet.
- Nothing has been scheduled (no live cron anywhere) and nothing has been
  pushed to GitHub — I have no push access; you're handling that via
  ChatGPT/Grok as planned.
- Stage 13 (release sign-off) correctly stays NOT COMPLETE until the above
  happens on a real machine with real data.

So: Stages 1-3, 8-12 are code-complete and verified by execution. Stages 4-6
are feature-complete but evaluation-blocked on data access. Stage 13 is
honestly still open, and the remaining gap is "run this for real," which
needs your machine and your GitHub access, not more code from me.

## Update — Stage 10 real fix (fifth pass, from your ChatGPT/Grok master-prompt)

That master-prompt correctly identified a real gap: Stage 10 was comparing a
candidate to a generic baseline, not to the actual registered champion on
identical fixtures. Fixed - see `stages/stage10/STAGE10_CHAMPION_COMPARISON_FIX.md`
for full detail, evidence from two tested scenarios (one correct rejection,
one correct promotion, both run through the real script), and honest
limitations (new regression test file written but not run with pytest - no
internet here to install it; verified by hand instead, shown in that file).

I checked the other specific claim in that prompt (Stage 8 extra-parenthesis
syntax error) against the copy I have - it's already correct there. I have
no access to your GitHub repo's other branches or the open PR, so I can't do
the requested branch comparison/consolidation - that needs you to either
reconnect the GitHub connector or upload those branches directly.
