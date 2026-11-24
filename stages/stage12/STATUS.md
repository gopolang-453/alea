# Stage 12 — Reliability / security

**Status (24 Nov 2026):** EXERCISED AGAINST THE ACTUAL LEDGER AND THE ACTUAL HTTP SERVICE (locally and in CI). NOT YET A PRODUCTION DEPLOYMENT: no always-on host, and monitoring is limited to CI alerts.

`scripts/recovery_drill.py --ledger <ledger.sqlite>` runs 17 checks. The real store is only read; every destructive step runs on copies.

| Check | What it proves |
|---|---|
| source_integrity | the real ledger passes `PRAGMA integrity_check`, append-only triggers and fingerprint checks |
| backup_created_and_verified | online SQLite backup plus manifest (SHA-256, fingerprint) |
| restore_ok | the restore reproduces the exact forecast fingerprint |
| interrupted_write_rolled_back | a writer killed mid-transaction (`os._exit`) leaves the ledger unchanged and valid |
| truncated_file_detected / garbage_file_detected | corrupted stores are detected |
| missing_file_detected | a missing store is refused and never silently recreated |
| restore_after_corruption | recovery from corruption to the exact fingerprint; the corrupted file is preserved |
| restore_rejects_tampered | a tampered backup is refused and the destination left untouched |
| restore_refuses_history_loss | an older backup cannot overwrite newer forecasts |
| duplicate_prevention_after_restore | the restored store still rejects overwrites and re-forecasts of the same match |
| append_only_after_restore | UPDATE/DELETE triggers are still enforced |
| service_healthy_on_restored | the real HTTP server returns 200 on the restored store |
| service_refuses_corrupt_store | the real HTTP server returns 503 on a corrupt store |
| no_secrets_in_repo_or_logs | secret scan of the tree and the run logs |
| failure_is_logged | a missing ledger gives exit 3, a failed-run record and a log file |
| freshness_gate | stale data is classified stale and the service degrades |

- **Local run on the real ledger (24 Nov 2026):** 17/17 pass, report in `results/stage12/ledger_drill_2026-11-24.json`. The ledger is byte-identical afterwards.
- **CI:** the same drill runs on the committed ledger in "ALEA tests", and on the live ledger in the weekly workflow.
- **Tests:** `tests/test_stage12_ledger_ops.py` and `tests/test_stage12_recovery_drill.py` (artifact drill, 6 checks).
- **Operator tools:** `scripts/ledger_admin.py backup|restore|integrity`. Recovery steps are in `docs/OPERATIONS.md`.
