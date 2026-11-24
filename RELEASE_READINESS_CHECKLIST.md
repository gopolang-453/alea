# ALEA 3.0 release-readiness checklist (24 Nov 2026)

Each mark is backed by a command or run listed in the consolidated report. "Tested on real data" means the real ledger, the real 2019-20…2026-27 data, or a live source fetch, not synthetic fixtures. **Stage 13 is NOT complete:** v3.0.0 must not be tagged while any "Still blocked" cell is non-empty.

| Item | Implemented | Tested locally | Tested in CI | Tested on real data | Deployed | Still blocked |
|---|---|---|---|---|---|---|
| Frozen champion v2.4.1 (hash-verified by pipeline, API, CI) | yes | yes | CI_TESTS | yes | n/a | — |
| Historical import, OpenFootball CC0 2019-20…2025-26 | yes | yes | yes (Stage 9 workflow) | yes (2,660 matches) | n/a | — |
| Current-season results, Wikipedia CC BY-SA (fetch, parse, provenance) | yes | yes | CI_WEEKLY | yes (rev 1387424026, 110/110 agree with football-data) | via workflow | — |
| Data gates: completeness, freshness, team names, cross-source agreement | yes | yes | CI_TESTS | yes | via workflow | — |
| Settlement, fixture matching, duplicate prevention | yes | yes | CI_TESTS | partly: 0 matches settled yet (first forecasts kick off 28 Nov 2026) | via workflow | real settlement not yet observed |
| Postponed / rescheduled / cancelled / abandoned / conflicting / missing results | yes | yes (synthetic) | CI_TESTS | no real case yet | via workflow | — |
| Append-only ledger, per-forecast model version and training fingerprint | yes | yes | CI_TESTS | yes | `prospective-ledger` branch | — |
| Prospective metrics (LL, Brier, RPS, accuracy, CIs, n) and challenger comparison | yes | yes | CI_TESTS | runs on the real ledger, but n=0 settled | via workflow | needs ≥300 paired settled fixtures |
| Weekly workflow (retrieve, validate, fit, forecast, record, report, artifacts, alert) | yes | yes (step rehearsal on a copy) | CI_WEEKLY | CI_WEEKLY_REAL | **no**: schedule fires only from `main` | merge to `main` (owner permission) |
| Stage 11 API (endpoints, validation, errors, logging, metrics, no model switching) | yes | yes (20 tests and a real HTTP server) | CI_TESTS; container CI_DOCKER | yes (real ledger) | **no** public host | choose a host and deploy |
| Stage 12 drill: backup/restore, interrupted write, corruption, missing DB, duplicates after restore, secrets, failure logging, freshness | yes | yes, 17/17 on the real ledger | CI_TESTS; CI_WEEKLY | yes (real ledger and real HTTP service) | runs every scheduled run | always-on monitoring of a deployed service |
| Champion vs challengers on identical fixtures | yes | yes | yes (Stage 9 workflow) | yes (n=1,900 dev / 380 holdout) | n/a | — |
| Champion vs closing market | yes | yes | no (odds file is local-licensed) | yes (n=1,140) | n/a | — |
| Stage 4 xG | scaffolding only | unit tests | yes | no | no | licensed, timestamped xG source |
| Stage 5 players / injuries / lineups | scaffolding only | unit tests | yes | no | no | licensed source with availability timestamps |
| Stage 6 context | scaffolding only | unit tests | yes | no | no | full-schedule (all competitions) licensed data |
| Documentation (install … backtests) | yes | reviewed against the code | n/a | n/a | n/a | — |
| Redistribution of committed odds files (`results/predictions_*odds*.csv`) | — | — | — | — | — | owner decision: remove or get permission |
| **Stage 13 final acceptance** | no | — | — | — | no | all rows above |
