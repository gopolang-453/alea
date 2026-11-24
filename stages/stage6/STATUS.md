# Stage 6 — Advanced contextual factors

**Status (24 Nov 2026): BLOCKED (data).** The calculators below are tested scaffolding and are not used by the champion. No source was found with a licence permitting storage and model training, continuous PL coverage, and per-record availability timestamps. The findings and the requirements to unblock are in `docs/DATA_SOURCES_AND_LICENSING.md`.

## Scaffolding: feature contracts (tested in isolation)

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
