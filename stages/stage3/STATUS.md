# Stage 3 — Team strength, Elo and form

## Status: FEATURES COMPLETE; PROBABILITY CANDIDATES REJECTED ON HOLDOUT

### Implemented
- Leakage-safe Elo (date-batched updates)
- Recent form and head-to-head helpers
- `fixture_team_features` with explicit `before_date` cutoff
- Unit tests passing

### Holdout evaluation (identical 380 fixtures as Stage 9 champion)

| Model | Log loss | Brier | Accuracy | Decision |
|-------|----------:|------:|---------:|----------|
| DC v2.4.1 (champion) | **0.9427** | **0.5569** | **0.579** | **retain** |
| Elo alone | 0.9591 | 0.5670 | 0.555 | reject |
| DC + Elo equal weight | 0.9457 | 0.5582 | 0.574 | reject |

Evidence: `results/stage3_stage8_eval.json` (2026-11-20)

### Decision
Elo/form remain available as **features** for future work. They are **not** enabled in the production probability path. No hyperparameter search was run on the holdout.
