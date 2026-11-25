# ALEA 3.0 release-readiness checklist (final audit, 24 Nov 2026)

Each mark is backed by a command or run in `ALEA_3.0_FINAL_AUDIT_2026-11-24.md`. "Tested on real data" means the real ledger, the real 2019-20…2026-27 data or a live source fetch, not synthetic fixtures. "Deployed" means running for real users, not a container started in CI.

**Stage 13 is NOT complete. Do not tag v3.0.0** while any "Still blocked" cell is non-empty.

| Item | Implemented | Tested locally | Tested in CI | Tested on real data | Deployed | Still blocked |
|---|---|---|---|---|---|---|
| Frozen champion v2.4.1 (SHA-256 `4cfc6108…f022a`, checked by pipeline, API and CI) | yes | yes (`sha256sum -c SHA256SUMS.txt`) | yes | yes | n/a | — |
| Historical import, OpenFootball CC0 2019-20…2025-26 | yes | yes | yes (Stage 9 workflow) | yes (2,660 matches) | n/a | — |
| Current-season results, Wikipedia CC BY-SA (fetch, parse, revision id, URL, retrieval time) | yes | yes | yes | yes (rev 1387424026, 110 results, dry run 24 Nov) | via workflow | — |
| Data gates: completeness, freshness (break-aware, 576 h ceiling), team names, cross-source agreement | yes | yes | yes | yes (dry run on live ledger copy: fresh, 50/50 OpenFootball agree) | via workflow | — |
| Settlement, fixture matching, duplicate prevention | yes | yes (synthetic) | yes | partly: 0 real matches settled (first kick-offs 28 Nov 2026) | via workflow | **real settlement not yet observed** |
| Postponed / rescheduled / cancelled / abandoned / conflicting / missing results | yes | yes (synthetic) | yes | no real case yet | via workflow | no real case observed |
| Append-only ledger, per-forecast model version, training fingerprint | yes | yes | yes | yes | `prospective-ledger` branch | — |
| Commit gate (`verify_ledger_update.py`): no corrupt/incomplete/rewritten ledger committed | yes | yes (accept, reject, missing, corrupt, empty) | in this push | yes (dry run: gate ok on live copy) | workflow | first live gated run after merge |
| Rerun / interruption idempotence | yes | yes (interrupted run + rerun test; dry rerun kept 10, added 0) | yes | yes | — | — |
| Dry run cannot write or push (copy, no credentials, byte-identical check) | yes | yes (static workflow test) | push-triggered dry run | yes | — | — |
| Prospective metrics, paired ISO-week bootstrap, pairing rules | yes | yes (hand-checked formulas) | yes | runs on real ledger, n=0 settled | via workflow | **≥300 paired settled fixtures** |
| Weekly workflow (15 steps, alert on failure) | yes | yes (dry run on a copy) | yes (dry runs on branch) | yes (24 Nov live run seeded 10 forecasts) | **no**: schedule fires only from `main` | merge PR #4 (owner) |
| Stage 11 API (read-only, no path leakage, attribution, no model switching) | yes | yes (26 tests; real HTTP server on live ledger copy, hash unchanged) | yes; container 200/503 | yes | **no public host** | choose host (`docs/HOSTING_OPTIONS.md`), deploy |
| Stage 12 drill (17 checks) and restore history-loss guard (all tables) | yes | yes, 17/17 on live ledger copy | yes | yes | runs each workflow run | monitoring of a deployed service; production reliability not demonstrated |
| Champion vs challengers on identical fixtures | yes | yes | yes | yes (n=1,900 dev / 380 holdout) | n/a | — |
| Champion vs closing market (aggregates only; odds user-supplied via `--odds`) | yes | yes (synthetic CLI tests; local rerun identical) | synthetic tests only | yes (n=1,140; market better) | n/a | — |
| Odds files removed from the tree | yes | yes | yes | n/a | n/a | **history cleanup needs owner approval** (`docs/ODDS_DATA_HISTORY_CLEANUP.md`) |
| Licensing position for public outputs | documented with attribution | n/a | n/a | n/a | n/a | **legal review** before commercial use |
| Stage 4 xG | scaffolding only | unit tests | yes | no | no | licensed, timestamped xG source |
| Stage 5 players / injuries / lineups | scaffolding only | unit tests | yes | no | no | licensed source with availability timestamps |
| Stage 6 context | scaffolding only | unit tests | yes | no | no | licensed all-competition schedule |
| Documentation | yes | reviewed against code | n/a | n/a | n/a | — |
| **Stage 13 final acceptance** | no | — | — | — | no | all rows above |
