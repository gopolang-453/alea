# Stage 3 — Team strength and form features

**Branch:** `repair/alea-3.0-end-to-end`  
**Date:** 19 November 2026

## Status: PARTIAL

### Accepted (feature builders)

| Requirement | Evidence |
|-------------|----------|
| Elo updates only after result availability | date-batched, `before_date` filter |
| Same-day matches do not update each other | batch logic in `elo_ratings` |
| Form / H2H exclude target fixture date | `before_date=fixture_date` |
| Missing history returns `None` (not invented) | tests |
| Works with PersistentDataStore snapshots | `test_stage1_persistent_features.py` |

### Still open (required for full Stage 3 acceptance)

1. **Probability mapping** — Elo difference is not yet converted to H/D/A probabilities via a training-only fitted mapping. The fixed 0.25 draw shortcut is forbidden.
2. **Evaluation against production MLE** — Elo-only, form-only and Elo+form must be scored on the same out-of-sample fixtures as the production Dixon-Coles MLE under the Stage 9 protocol.
3. **Wiring into production prediction path** — `fixture_team_features` is not yet consumed by the production predictor or the Stage 9 runner.

These items are blocked on Stage 9 real-data walk-forward, not on the feature code itself.

### Decision

Feature extraction is accepted.  
Do **not** claim Stage 3 complete until the evaluation and probability mapping exist.
