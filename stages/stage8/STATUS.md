# Stage 8 — Probability calibration

## Status: IMPLEMENTED; NOT ENABLED IN PRODUCTION

### Implemented
- Multiclass temperature scaling
- Strict out-of-sample cutoff enforcement (`cutoff < match date`)
- Unit tests passing

### Development fit (n=559)
- Temperature T = 1.200
- Development log loss: 0.9907 → 0.9870 (improvement 0.0037)

### Holdout application (n=380, T frozen from development)
- Uncalibrated DC log loss: **0.9427**
- Calibrated log loss: **0.9480** (worse)

### Decision
Do **not** apply temperature scaling in production. The small development gain did not generalise. Champion remains uncalibrated `alea-dc-v2.4.1`.

Evidence: `results/stage3_stage8_eval.json`
