# Odds data: remaining exposure and history cleanup (requires owner approval)

**Status (24 Nov 2026): NOT EXECUTED.** Nothing in this procedure has been run. History rewriting and force-pushing need the owner's explicit permission.

## What was exposed

- **Files:** `results/predictions_closing_odds.csv`, `results/predictions_early_odds.csv` and `results/predictions_closing_dev.csv`. These hold per-match Bet365 odds (raw and devigged) from football-data.co.uk, whose terms ([football-data.co.uk](https://football-data.co.uk/contact.php)) allow personal/academic use but not redistribution.
- **First committed:** in `8fbba97` ("Publish ALEA v2.4.1 and the unreleased dev repair.", 13 Nov 2026).
- **Repository visibility:** public (checked 24 Nov 2026), with 0 forks.

## Where the files still exist after PR #4's removal commit

| Location | Present? | Who can remove it |
|---|---|---|
| Tree of `repair/alea-3.0-consolidated` (PR #4 head) | No (removed in the audit commit) | — |
| Tree of `main` | Yes, until PR #4 is merged | Merging PR #4 (owner) |
| Trees of `repair/alea-3.0-claude-verified`, `repair/alea-3.0-end-to-end`, `repair/alea-3.0-integrated`, `repair/stage13-evidence-and-pipeline`, `session/2026-11-23-audit-docs` | Yes | Owner (delete or rewrite branches) |
| History of every branch above, including `main` and PR #4 | Yes, from `8fbba97` onward | History rewrite + force-push (owner) |
| `refs/pull/1..4/head` (read-only pull request refs) | Yes | Only GitHub Support |
| Cached views, the API, and existing clones of the public repository | Possibly | Not controllable; GitHub Support can purge caches |
| `prospective-ledger` data branch | No (verified: 0 matching files) | — |

## Recommended procedure (run only after approval)

1. **Decide the scope.** Either close and delete the obsolete branches first (PRs #1–#3 and their branches are superseded by PR #4), or rewrite every branch.
2. **Back up.** `git clone --mirror https://github.com/gopolang-453/alea.git alea-backup.git` and keep it offline and private. It contains the files and must not be published.
3. **Rewrite on a fresh mirror clone:**

   ```bash
   git clone --mirror https://github.com/gopolang-453/alea.git alea-clean.git
   cd alea-clean.git
   pip install git-filter-repo
   git filter-repo --invert-paths \
     --path results/predictions_closing_odds.csv \
     --path results/predictions_early_odds.csv \
     --path results/predictions_closing_dev.csv
   ```

   Every commit SHA from `8fbba97` onward changes. The frozen champion file's content and SHA-256 do not change; check this with `sha256sum -c SHA256SUMS.txt` on a checkout afterwards.
4. **Check before pushing.** `git log --all -- results/predictions_closing_odds.csv` must be empty. Then run the full test suite on a checkout of the rewritten PR branch.
5. **Force-push** all branches (`git push --force --mirror` from the cleaned mirror; GitHub rejects updates to `refs/pull/*`, which is expected). The `prospective-ledger` branch is unaffected by the filter, but its SHAs must be verified unchanged. If they changed, stop and restore from the backup: the ledger branch must never be rewritten.
6. **Contact GitHub Support** to remove cached views and the `refs/pull/*` refs (follow GitHub's "Removing sensitive data from a repository" guide), giving the commit SHAs and file paths.
7. **Re-clone.** Collaborators must re-clone; old clones would reintroduce the files on push.
8. **Re-open PR #4** if the force-push closes it, and re-run CI.

## Consequences to weigh

- PR review comments and CI run references to old SHAs become dangling.
- Anyone who cloned before the rewrite keeps a copy. A rewrite reduces further distribution; it cannot recall copies already made.
- **Not legally cleared.** Neither this cleanup nor the removal from the latest commit establishes that the earlier publication was permitted, or that it is now cured. If this matters, ask football-data.co.uk for retrospective permission or take legal advice.

## Alternative without rewriting

Leave history as is, merge PR #4 so `main` no longer contains the files, and delete the superseded branches. The files then remain reachable only through old commits and the pull request refs. This is less effective, but it needs no force-push.
