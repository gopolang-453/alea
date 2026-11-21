# Stage 13 — Final acceptance

## Status: NOT COMPLETE

The repair branch now contains first-pass implementations and tests for the missing stage modules, but final acceptance requires evidence from a real, reproducible production run and integration into a running service.

## Current acceptance blockers

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
