# Stage 13 — Final acceptance

## Status: NOT COMPLETE

### Current blockers

1. **Stage 9 real-data artifact** — OpenFootball import and the production MLE runner are fixed (FC/AFC strip + `clean_matches`). A completed multi-season walk-forward + 2023-24 holdout report has not yet been committed as evidence.
2. **Stage 3 evaluation** — Elo/form features are not yet scored against the production MLE on identical out-of-sample fixtures.
3. **Stages 4–6** — Remain disabled; no licensed timestamped historical sources.
4. **Stages 10–12** — Code and unit tests exist; not an integrated deployed pipeline.
5. **No live scheduler or production service.**

### Release rule (unchanged)

Do not mark Stage 13 complete, promote a champion, or tag `v3.0.0` until:

- Integrated-branch CI is green.
- A reproducible Stage 9 development + holdout report exists with log loss, Brier, RPS, accuracy and uncertainty.
- Feature decisions are evidence-backed or explicitly rejected.
- Operational recovery checks for the claimed scope are exercised.

A passing unit-test suite alone is not Stage 13.
