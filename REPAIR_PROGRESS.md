# ALEA 3.0 repair progress

**Branch:** `repair/alea-3.0-integrated`  
**Base:** `main` at `18e2e94c0fdfe1a43376e36e31c6f7c1db85d73d`  
**Status:** implementation in progress; Stage 13 remains OPEN.

## Implemented on this branch

- Built on the existing Stage 1 `PersistentDataStore`; preserved season metadata in result snapshots and tightened result/date/team/score validation.
- Added a licensed OpenFootball JSON parser/import command. Date-only results are delayed by 36 hours by default. Raw JSON, manifests and SQLite data stay outside Git.
- Replaced the broken Stage 9.1 test with an offline parser + SQLite integration test.
- Added exact full-distribution Dixon–Coles 1X2, BTTS and totals functions; finite score-grid aggregations are explicitly documented as grid-conditional.
- Added Stage 3 Elo, form and head-to-head features with strict prior-date filtering and same-day batch handling.
- Fixed Stage 4–6 package imports. Missing xG now returns `None`; rolling xG is ordered by match date; Stage 5 no longer fabricates numeric player-impact weights.
- Hardened Stage 7 probability/weight/fixture validation.
- Added Stage 8 out-of-sample temperature calibration with per-prediction training-cutoff checks.
- Added Stage 9 production MLE expanding-window runner with a separate final-season holdout, availability-time filtering, per-match provenance, development-only calibration, and paired ISO-week bootstrap uncertainty.
- Added a GitHub Actions workflow to fetch five OpenFootball seasons and run the production MLE backtest as an artifact-producing job.
- Added Stage 10 evidence-gated model registry and rollback.
- Added Stage 11 pre-kickoff prediction response and immutable prediction history.
- Added Stage 12 artifact checksum, backup/restore, data-freshness and high-confidence working-tree secret checks.
- Added focused offline regression tests and expanded GitHub Actions CI.

## Not yet verified / not yet complete

- The latest integrated-branch CI run must complete successfully. Earlier CI on the older repair branch passed 15 tests, but that does not validate this integrated branch.
- The OpenFootball historical dataset has not yet been fetched/imported by the new integrated-branch workflow.
- The production MLE walk-forward and final-season holdout have not yet been run on the imported dataset. No new real-data performance numbers are claimed.
- Elo/form have not yet been evaluated as probability models against the production MLE on identical out-of-sample fixtures.
- xG, injuries, lineups and context remain disabled as predictive inputs until suitable licensed, timestamped historical sources are connected.
- There is no dependable live fixture/results scheduler or deployed service.
- The new Stage 10–12 modules are tested contracts/utilities; they are not yet a fully deployed production pipeline.

## Acceptance rule

Do not mark Stage 13 complete, promote a new champion, or tag v3.0.0 until the integrated branch passes CI, the real-data MLE walk-forward and untouched holdout are reproducible, feature comparisons are evidence-backed, and operational recovery checks pass.
