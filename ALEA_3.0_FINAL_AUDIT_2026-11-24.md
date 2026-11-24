# ALEA 3.0 final audit, remediation and release preparation (24 Nov 2026)

- **Scope:** PR #4 (`repair/alea-3.0-consolidated` against `main`), together with the live `prospective-ledger` data branch.
- **Constraints:**
  - The frozen champion `alea_predictor_v2_4_1.py` (SHA-256 `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`) was verified before and after the work and is unchanged.
  - The registry champion is unchanged.
  - No challenger was promoted, and the promotion criteria are unchanged.
  - Nothing was merged to `main` or deployed.
  - History was not rewritten.
  - The data branch was not written by hand.

## Findings register

Severity: HIGH = can corrupt the ledger, bias the evaluation or breach a licence; MEDIUM = wrong or unsafe behaviour under realistic conditions; LOW = hardening or documentation.

| # | Severity | File | Problem | Change | Verification |
|---|---|---|---|---|---|
| 1 | HIGH | `scripts/run_prospective_forecast.py` | The freshness gate treated any 240 h gap since the latest result as stale. The 2026-27 list has scheduled gaps of up to 503 h (international breaks), so runs would have been blocked and the round after each break never forecast. | A feed is stale only if fixtures were played since its latest result, with a hard ceiling of 576 h (`MAX_SCHEDULED_BREAK_HOURS`). | `test_international_break_is_not_treated_as_stale_feed`, `test_feed_missing_played_fixtures_is_still_blocked`, `test_break_exemption_has_a_hard_ceiling`, `test_gate_blocks_stale_feed` |
| 2 | HIGH | `.github/workflows/weekly-prospective-forecast.yml` | Push-triggered runs on `repair/**` were live: only `inputs.dry_run` guarded the commit, and it is empty on push. | `LIVE` is true only for schedule or non-dry `workflow_dispatch` on `refs/heads/main`. Data checkout credentials are persisted only when live; the commit step requires `LIVE`. | static workflow test; push-triggered run on this branch reports dry mode |
| 3 | HIGH | workflow | There was no commit gate. A corrupt, truncated or rewritten ledger could be committed, because diagnostics and permission to commit were the same step. | New `stages/stage12/ledger_ops.verify_append_only_update` and `scripts/verify_ledger_update.py`. These run before the commit against a pre-run snapshot and refuse a missing or corrupt file, missing triggers, failed integrity or any changed or removed pre-existing row. The commit needs gate = 0 and pipeline ≠ 3. Dry runs also check that the real checkout is byte-identical. | `test_commit_gate_*` (accept, reject modified row, reject deleted row, missing, corrupt, empty, CLI exit codes); local dry run: gate ok |
| 4 | HIGH | workflow | `git add -A` could commit temporary, journal, pre-restore or other unexpected files to the public data branch. | Explicit allowlist. It refuses tmp, journal, WAL, SHM, pre-restore and secret-like names, and warns about files outside the list. | static workflow test |
| 5 | HIGH | `scripts/run_prospective_forecast.py`, `stages/stage9/prospective_evaluation.py` | A challenger could be added to an existing champion forecast after new results arrived, so it would be compared with the champion on a different information set. | Recording: a challenger is skipped (with an issue logged) if `training_matches` differs from the champion's run. Evaluation: pairs need the registry model version, both rows made pre-kickoff (effective kickoff) and equal `training_matches`; an unverifiable pair is excluded. | `test_late_challengers_need_the_champions_information_set`, `test_pairing_excludes_wrong_version_late_or_better_informed_challengers`; all 20 live challenger rows remain eligible |
| 6 | HIGH | `results/predictions_*odds*.csv`, `results/predictions_closing_dev.csv` | Per-match Bet365 odds from football-data.co.uk were redistributed in a public repository. | Removed from the tree. `compare_vs_market.py --odds` is required and user-supplied; it writes aggregates only and fails clearly (exit 2). History cleanup is documented and **not executed**. | 3 synthetic CLI tests; local rerun reproduced identical aggregates |
| 7 | MEDIUM | `stages/stage9/prospective_ledger.py` | `integrity_report` did not detect a duplicate match identity under different keys, challenger probabilities not summing to 1, or orphan challenger rows. | Added all three. | `test_integrity_detects_duplicate_match_and_orphan_challenger` |
| 8 | MEDIUM | `stages/stage12/ledger_ops.py` | The `restore_ledger` history-loss guard compared only champion fixture keys. An older backup lacking outcomes, observations, events, corrections or runs could silently replace them. | It compares every table and refuses unless `allow_history_loss` is set. | `test_restore_refuses_backup_missing_outcomes_or_observations` |
| 9 | MEDIUM | `scripts/run_prospective_forecast.py` | No integrity check was run after writing. | A post-write integrity report is recorded; on failure the run is marked failed and exits 3. | `test_post_write_integrity_failure_returns_3` |
| 10 | MEDIUM | `scripts/run_prospective_forecast.py` | `--crosscheck-csv` stores football-data.co.uk scores in the ledger, which would publish them if used in Actions. | Refused when `GITHUB_ACTIONS=true` (exit 2). | `test_crosscheck_csv_refused_in_github_actions` |
| 11 | MEDIUM | `stages/stage11/api.py` | Error bodies could include file paths and exception text. | Generic messages; details go to the server log only. | `test_errors_do_not_leak_filesystem_paths` |
| 12 | MEDIUM | API, reports | Attribution for CC BY-SA content was not visible in API responses or always present in reports. | An `attribution` object on data responses; a "Data sources and licences" section in every report. | API and report tests |
| 13 | MEDIUM | `scripts/run_prospective_forecast.py` | Provenance lacked retrieval timestamps and a revision-specific URL. | `retrieved_at` and the oldid URL for Wikipedia; URL and `retrieved_at` (file mtime, labelled) for fixtures. | provenance test; dry-run JSON |
| 14 | LOW | `scripts/recovery_drill.py` | `restore_rejects_tampered` passed on any exception, including unrelated crashes. | Only the intended `ReliabilityError` refusal counts. | drill 17/17 |
| 15 | LOW | `stages/stage11/STATUS.md` | Claimed that `prediction_service` "never existed"; it is a legacy library not used by the API. | Corrected. | review |
| 16 | LOW | `Dockerfile`, `docs/OPERATIONS.md` | The run example published on all interfaces. | `-p 127.0.0.1:8080:8080`. | review |
| 17 | LOW | workflow, `Dockerfile` | Actions are pinned by tag, not SHA; the base image is pinned by tag, not digest. | Documented (owner decision). | — |
| 18 | LOW | `stages/stage11/api.py` | `wsgiref` is single-threaded; each request runs `PRAGMA integrity_check`; `upcoming` shows listed, not rescheduled, kickoffs. | Documented; a reverse proxy is required for hosting. | — |
| 19 | LOW | operations | After the last round of the season, runs are blocked as stale (alerts) until the next season is configured. | Documented. | — |
| 20 | LOW | GitHub settings | `prospective-ledger` has no branch protection. | Documented (owner decision). | — |

### Checked and found correct (no change)

- **Time handling:** `london_to_utc` handles DST correctly (2026-10-25 and 2027-03-28). A missing time defaults to 15:00 London.
- **Ledger guards:** `record_prediction` duplicate and twin guards are correct. Append-only triggers are present on the live ledger.
- **Metrics:** LL, Brier (3-class sum), RPS (½ Σ over 2 cumulative terms) and accuracy match hand calculations.
- **Bootstrap:** the paired ISO-week block bootstrap (candidate − champion, percentile CIs) is correct.
- **Promotion rule:** n ≥ 300, LL CI upper < 0 and Brier diff ≤ 0 match `config/model_registry.json`.
- **Prospective features:** challenger Elo/form features use only results present in the snapshot at run time.
- **Wikipedia User-Agent:** descriptive, with a contact URL. Including "bot" is recommended but optional.
- **Model versions:** the live ledger holds only `alea-dc-v2.4.1`, both runs used `training_matches` 2770, and integrity is ok.

## Recovery drill: what the 17 checks prove

The drill exercises real code on scratch copies:

- online backup and manifest verification;
- restore;
- a writer killed mid-transaction, which rolls back;
- truncated, garbage-header and missing files, which are detected and never recreated;
- restore over corruption;
- tampered backups, which are refused;
- older backups, which cannot erase history;
- triggers and duplicate guards surviving a restore;
- the real HTTP service returning 200 on the restored store and 503 on a corrupt one;
- a secret-pattern scan;
- a missing ledger, which logs a failed run (exit 3);
- stale data, which is classified stale and reported as degraded.

What it does **not** prove:

- **Production reliability:** there is no deployed service, no uptime history and no off-site backup beyond git history and 90-day artifacts.
- **Content corruption:** corruption of record contents that leaves the SQLite structure valid is caught only by the fingerprint and manifest hash, not by `PRAGMA integrity_check`.
- **Absence of secrets:** the secret scan is pattern-based and cannot prove none are present.

## Stages 4–6

Reassessed against the requirement that a source have a written licence, storage and training permission, Premier League coverage, availability timestamps and historical depth. No source meets all of these without a paid agreement, so Stages 4–6 stay **BLOCKED**:

- StatsBomb open data is non-commercial and incomplete for the Premier League.
- FBref/Sports-Reference terms restrict automated collection.
- Lineups and injuries are only available close to kickoff, and no licensed source with availability timestamps is in hand.

See `docs/DATA_SOURCES_AND_LICENSING.md`.

## Market comparison (unchanged, not hidden)

The closing market beats the champion: LL difference champion − market **+0.0222 [+0.0122, +0.0317]**, n = 1,140; ECE champion 0.0176 vs market 0.0083. Odds are not used as model inputs. DC/Elo remains experimental (−0.0030 [−0.0108, +0.0048] on the holdout, not significant).

## Test results

See the PR #4 comment for this commit and `TEST_RESULTS.txt`.

Local results on the final tree (Python 3.14; CI uses 3.11):

| Command | Result |
|---|---|
| `python -m pytest -q` | 230 passed in 956.77 s |
| `python tests/run_all.py` | 44/44 test files passed |
| `python dev/tests/test_dev_repairs.py` | ALL DEV CHECKS PASSED |
| `python scripts/security_check.py` | no high-confidence secret patterns |
| `sha256sum -c SHA256SUMS.txt` | 3 files OK (including `alea_predictor_v2_4_1.py`) |
| `actionlint` 1.7.7 on all workflows | clean |
| `scripts/recovery_drill.py` on a copy of the live ledger | 17/17 |
| Pipeline dry run on a copy of the live ledger (fresh Wikipedia rev 1387424026 + fresh OpenFootball) | exit 0; status ok; 110 results, 50/50 agree with OpenFootball; freshness fresh (73 h); 10 forecasts already in ledger, 0 new, 0 challenger rows added; +1 run row |
| `scripts/verify_ledger_update.py` on that dry run | ok, no problems |
| `scripts/serve_api.py` real HTTP server on the live ledger copy | `/health` 200 (ok), status/upcoming/history/evaluation/metrics 200, `/admin` 404, bad params 400, POST 405; ledger SHA-256 `974338d9…72d6` identical before and after, and identical to `prospective-ledger` |

One failure was found and fixed during this audit. The first full run gave 228 passed and 1 failed: `test_gate_blocks_stale_feed` showed that the break exemption could hide a dead feed when the fixture list is incomplete. The gate gained the 576 h ceiling; the test was not changed.
