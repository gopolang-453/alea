# Stage 6 — Advanced contextual factors

## Status: FEATURE CONTRACTS COMPLETE AND TESTED

### Implemented and tested
- Weather for fixture (fail-closed)
- Venue info
- Referee tendencies (requires ≥5 prior matches)
- Manager-change flag within a lookback window
- Travel distance
- Derby flag

All functions are leakage-safe and return None/False when data is absent.

### Tests
- `tests/test_stage6_context.py` — **4 passed**

### Not yet claimed
Statistical evidence that any contextual feature improves predictions. These remain experimental until a comparative backtest is run.
