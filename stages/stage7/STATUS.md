# Stage 7 — Machine learning and model ensemble

## Status: CONTRACTS COMPLETE AND TESTED

### Implemented and tested
- PredictionRecord container
- Multiclass log loss and Brier score
- Equal-weight (or custom-weight) probability ensemble
- Best-model selection by log loss
- Validation that probabilities sum to 1

### Tests
- `tests/test_stage7_ensemble.py` — **7 passed**

### Not yet claimed
- Training of LightGBM, XGBoost, or any other model
- Out-of-sample evidence that an ensemble beats Dixon-Coles
- Calibration of ensemble weights on a validation set

The scaffolding is ready for real out-of-sample predictions to be plugged in.
