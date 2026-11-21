# Stage 10 — Automation status

**Previous date:** 18 November 2026 (contracts only)
**This update:** 20 November 2026 — refresh/retrain/compare/promote cycle wired and tested

## What changed this session

`stages/stage10/automation.py` (`ModelRegistry`) already existed and was
already correct (promotion gate, rollback, SHA-256 verification). It was not
previously called by anything that also fetched data and retrained - there
was no scheduled or schedulable path from "new results exist" to "champion
updated, or explicitly not."

`scripts/refresh_and_retrain.py` is that path. One run = one decision. It is
designed to be invoked by cron/launchd/Task Scheduler (example line in the
script's own docstring), not to run as a background daemon itself.

### Verified this session (synthetic SQLite store; no internet in this sandbox)

- **Run 1**, no champion yet: candidate trained, evaluated (28-fold
  walk-forward), promotion gate passed, promoted. Confirmed via printed
  "Promoted. Champion: ..." and the registry file.
- **Run 2**, identical data re-run: candidate's holdout log loss (1.0492) was
  not better than the already-promoted champion's (1.0492 - same data,
  correctly tied/not-improved) -> **correctly refused to promote**, registered
  the candidate for audit only, left the existing champion untouched. This is
  the actual "promote only if better" behaviour, not just a contract test -
  it was exercised and it did the right thing on a real non-improving case.
- Fail-closed paths (no internet, bad data, empty snapshot, registry errors)
  all `return` a non-zero exit code before touching the registry - checked by
  reading the code path, not re-run this session (would need a real failure
  injected to actually trigger).

## Pass condition status (updated)

- **10.1 Fixtures auto-update:** still not done - this repo only ever ingests
  final results (OpenFootball), never pre-match fixture lists. Unchanged by
  this session; would need a different source.
- **10.2 Results/stats auto-update:** **now schedulable**, not just manual.
  `refresh_and_retrain.py` calls the same duplicate-safe ingest Stage 1
  already had; running it on a schedule makes updates automatic. Still
  depends on OpenFootball's own update cadence (volunteer-maintained, not an
  SLA) and on the host actually having internet and being scheduled - neither
  of which this sandbox has, so the live schedule itself is not demonstrated,
  only the one-shot logic it would repeat.
- **10.3 Auto training + promote only if better:** **now real**, not
  contract-only. Verified in both directions this session (promotes a
  genuine improvement; refuses a non-improvement) using synthetic data. Not
  yet run against real EPL data (needs internet).
- **10.4 Recovery:** unchanged - contract-tested (`rollback()` unit test),
  not re-exercised this session.

## Still not production

- No live fixture feed (10.1).
- Not actually scheduled anywhere (no crontab installed - that's an
  environment action for you to take, on a machine with internet; see the
  script's docstring for the line to use).
- Not run against real data yet.
- 10.4 rollback not re-verified this session.

**Stage 10 is closer but still not complete.** The automation logic is now
real and tested both ways (promote / correctly-refuse); what's left is
connecting it to a live fixture source and an actual schedule, and running it
once for real.
