# Stage 13 — Final acceptance

## Status: NOT COMPLETE

The repair branch now contains first-pass implementations and tests for the missing stage modules, but final acceptance requires evidence from a real, reproducible production run and integration into a running service.

## Update 24 Nov 2026 (second pass)

Stage 13 is still **NOT COMPLETE**. See `RELEASE_READINESS_CHECKLIST.md`.

- **Now implemented and tested:**
  - prospective settlement and evaluation;
  - a licensed results source (Wikipedia CC BY-SA plus OpenFootball CC0);
  - the scheduled workflow with alerting;
  - the API (with its container);
  - the ledger backup/restore drill against the real store and service.
- **Still open:**
  1. No public deployment of the API.
  2. The schedule fires only after the workflow is merged to `main`.
  3. Prospective evidence is too small: 10 forecasts, 0 settled. The promotion rule needs 300 paired settled fixtures.
  4. Stages 4–6 are blocked for lack of licensed, timestamped data.

## Update 24 Nov 2026

See `ALEA_3.0_STATUS_REPORT_2026-11-24.md`. Blocker 1 is resolved: the production MLE walk-forward has run on 7 real seasons (holdout 2025-26) and its evidence is in `results/stage9_mle/`. Blocker 3 is resolved negatively: Elo/form were evaluated on identical fixtures and none was accepted. Blocker 4 is resolved: calibration was evaluated and is gated off. Blockers 5–7 (automation, service, operational reliability) remain open. Prospective forecasts are now recorded in `results/prospective/ledger.sqlite`.

## Original acceptance blockers (21 Nov 2026)

1. **Production MLE walk-forward has not yet run on the imported historical dataset.** The Stage 9 workflow has been added to fetch five OpenFootball Premier League seasons, run the v2.4.1 MLE in expanding windows, and save a report/prediction artifact. Until that workflow completes successfully, no new real-data result is claimed.
2. **The walk-forward must respect information availability.** Training rows are now filtered by availability timestamp at or before prediction cutoff, not merely by match date. The regression suite includes a test for this.
3. **Feature evidence remains incomplete.** Stage 3 Elo/form features exist, but they have not yet been evaluated as probability models against the production MLE on identical out-of-sample fixtures. xG, injuries, lineups and context remain disabled as predictive inputs until timestamped historical sources are available.
4. **Calibration is not yet accepted.** Temperature scaling is fitted on development-period out-of-sample predictions only. It is selected only from development evidence; final-season holdout results must be reviewed.
5. **Automation is not deployed.** The model registry, evidence-gated promotion and rollback utilities exist, but no production scheduler or live results updater is running.
6. **The prediction service is not deployed.** A traceable prediction response and immutable history store exist as code; there is no running web/API interface.
7. **Reliability is not fully operational.** Checksum, backup/restore, freshness and working-tree secret-scan utilities exist, but continuous monitoring and tested operational recovery are not deployed.

## Release gate

Do not mark Stage 13 complete, promote a model, or tag v3.0.0 until:

- Integrated-branch CI passes.
- The five-season historical import completes with valid team IDs, 1,900 expected completed matches, no duplicate fixtures and reproducible fingerprints.
- Production MLE development walk-forward and the untouched 2023/24 holdout complete without date or availability leakage.
- The final report includes log loss, Brier, RPS, accuracy, calibration and paired block-bootstrap uncertainty.
- Elo/form and any other feature are retained only after identical-fixture out-of-sample evidence.
- Model promotion is compared against a registered current champion, not an arbitrary benchmark.
- Prediction service, automation and recovery checks are integrated and exercised.

A passing unit-test suite is necessary but not sufficient for Stage 13.
