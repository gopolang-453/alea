# Prospective evaluation: rules (pre-registered 24 Nov 2026)

The prospective ledger is the only untouched test set. These rules are fixed before any outcome is scored. Change them only by commit, with a stated reason.

## Ledger (`stages/stage9/prospective_ledger.py`)

### Append-only

SQLite triggers reject `UPDATE` and `DELETE` on every table:

- `predictions`
- `outcomes`
- `challenger_predictions`
- `fixture_events`
- `result_observations`
- `outcome_corrections`
- `data_quality_issues`
- `runs`

A forecast is never overwritten after it is recorded, and therefore never after kickoff.

### Per forecast

Each champion forecast records:

- `fixture_key` (`YYYY-MM-DD|home|away`, canonical names)
- `predicted_at` and the listed `kickoff_at`
- H/D/A probabilities, which must sum to 1 within 1e-6
- `model_version` and `code_sha`
- `training_data_sha256` and `training_matches`
- the results-source revision

### Pre-kickoff only

- `record_prediction` refuses `predicted_at >= kickoff_at`.
- The pipeline additionally requires a lead of at least 48 h (OpenFootball dates can be off by ±2 days).

### Duplicate prevention

- **Same fixture key:** the same payload is a no-op. A different payload raises an error.
- **Same season and pairing, different date:** refused. A rescheduled fixture is never forecast twice.

### Fingerprint

The SHA-256 covers the ordered champion forecasts. Challengers have their own fingerprint.

## Settlement (`observe_and_settle`)

1. Every source observation is stored in `result_observations` with its source and revision.
2. If all observations agree, the outcome is recorded once. Repeat observations are no-ops, so a result cannot be settled twice.
3. Two observations that disagree, or a new observation that differs from the settled outcome, create a `conflict`. The fixture is excluded from scoring until an operator records a correction (`ledger_admin.py correct`). Both the original rows and the correction are kept.

## Fixture status (`fixture_status`)

| Status | Scored? | Rule |
|---|---|---|
| settled | yes | an outcome exists and there is no open conflict. A match rescheduled to a later time stays valid |
| void | no | CANCELLED / AWARDED / VOID event, or rescheduled to a kickoff at or before `predicted_at` |
| conflict | no | sources disagree and there is no later correction |
| postponed | no (outstanding) | POSTPONED event and no new date |
| abandoned | no (outstanding) | ABANDONED and no replay result yet |
| pending | no (outstanding) | before kickoff + 2 h + 60 h grace |
| overdue | no (outstanding, flagged) | after the grace period with no result |

Postponements are detected automatically: an isolated missing result while at least 5 results exist for fixtures listed at least 3 days later. They are logged as `suspected_postponement` and do not block the run. Anything else that is missing blocks the run.

## Metrics and comparison (`stages/stage9/prospective_evaluation.py`)

- **Metrics on settled fixtures:** log-loss, Brier (3-class sum), RPS and accuracy, with ISO-week block-bootstrap 95% CIs (2,000 resamples, fixed seed) and sample sizes.
- **Challengers:**
  - Compared on exactly the fixtures where both the champion and the challenger have a forecast.
  - Paired differences are challenger minus champion, so negative favours the challenger.
- **Promotion rule** (`config/model_registry.json`):
  - At least 300 paired settled fixtures.
  - LL-difference CI upper bound below 0.
  - Brier difference ≤ 0.
  - Meeting the rule only makes a challenger eligible for human review. Nothing is promoted automatically.
- **Report:** settled, outstanding (by status), void and conflicting forecasts, plus the data-quality issues logged.
