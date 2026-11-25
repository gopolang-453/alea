# ALEA web app 1.0: release-readiness report (25 Nov 2026)

Branch `feature/alea-web-app`, built on PR #4 (`repair/alea-3.0-consolidated` at `344cb6b`). Not pushed.

## Verdict

ALEA is a working application. It serves a mobile-first website with the frozen champion's real forecasts from the live ledger. It is not yet reachable from the internet. That needs two owner actions:

1. Merge PR #4 and then this branch into `main`, so the schedule runs.
2. Create a hosting account (Fly.io recommended, about $2.19/month) and deploy.

## What was tested (actual results)

| # | Test | Result |
|---|---|---|
| 1 | Full pytest suite | **269 passed** (230 existing + 32 web app + 7 ledger sync) |
| 1 | `tests/run_all.py` (all test files) | 46/46 passed |
| 2 | API: fixtures endpoint, detail fields, errors, security headers, static serving, traversal, methods; real HTTP server | passed (in the suite) |
| 3 | Fixture retrieval | Real OpenFootball and Wikipedia data on a copy of the live ledger (`--now 2026-11-27T06:00Z`): 110 fixtures written |
| 4 | Champion prediction | The same dry run made 10 new forecasts for 2 Dec with expected goals and scorelines from the frozen `predict()`. The 1X2 guard passed, and a mismatch aborts the run (tested) |
| 5 | Probability sums | Ledger rows sum to 1. Displayed percentages always sum to 100 (largest remainder, tested), checked on every card in the browser |
| 6 | Missing data and API errors | Missing fixture file, corrupt file, bad parameters, unknown match, offline, timeout and server down all give useful messages without paths (tests and browser) |
| 7 | Mobile interface | Chromium emulation of iPhone 13, iPhone SE, iPad Mini and a 1366 px desktop, light and dark. No horizontal overflow, nothing under 12 px, 44 px tap targets |
| 8 | Historical integrity | Existing rows are unchanged after the dry run, there is no backfill (tested), `recovery_drill` passed, and the sync refuses rollbacks or rewritten forecasts (tested) |
| 9 | Workflow without touching the live ledger | The dry run used a copy, and the live copy's hash is unchanged (`974338d9…`). The commit gate passed. actionlint is clean |
| 10 | Secrets and restricted data | `security_check.py` passed. There are no odds files in the tree and no third-party hosts in `web/` (tested) |
| — | Ledger sync against the real public data branch | The downloaded ledger is byte-identical to `prospective-ledger@51ea938`, and `/health` reports ok |
| — | Champion integrity | `sha256sum -c SHA256SUMS.txt` OK |

## Not tested (stated plainly)

- **Real Safari/WebKit and a real iPhone.** WebKit is not available on this build machine, so the layout was checked only in Chromium emulation. Please open the private preview on your iPhone.
- **Docker build and container run.** Docker was not available locally. The CI smoke test builds the image and checks `/`, the CSP, a static asset, traversal, `/health` and the API on push.
- **A real scheduled GitHub Actions run.** Schedules fire only from `main`.
- **Real settlement of finished matches.** The first forecast kick-offs are on 28 Nov 2026.
- **A public deployment.** None was made, by design.

## Blockers to a public release (owner decisions)

1. **Merge PR #4, then this branch, before Fri 27 Nov 06:00 UTC.** That is the only scheduled run that forecasts the 2 Dec round. After that, the next runs are 1 Dec and 4 Dec.
2. **Hosting account and payment** (`docs/HOSTING_OPTIONS.md`, `fly.toml`).
3. **Licensing position for public outputs** (`docs/DATA_SOURCES_AND_LICENSING.md`). Non-commercial use with attribution is assumed.

Unchanged and still open:
- Stages 4–6 remain blocked on licensed data.
- 300 paired settled fixtures is the promotion and validation minimum and will not be reached before the 2027-28 season.
- The closing market beats the champion by +0.022 log loss (95% CI +0.012 to +0.032, n=1,140), and the app says so.
