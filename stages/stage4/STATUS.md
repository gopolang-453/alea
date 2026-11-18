# Stage 4 — Expected goals (xG)

## Status: FEATURE CALCULATORS COMPLETE AND TESTED

Pass condition (partial): xG features must be leakage-safe and fail closed when data is missing.

### Implemented and tested
- Rolling team xG for/against (last n matches)
- Home/away venue filter
- Per-fixture xG lookup
- xG over/underperformance (goals − xG) requiring paired result + xG records
- All functions respect `as_of` and return empty/None when data is absent

### Tests
- `tests/test_stage4_xg.py` — **5 passed**

### Not yet claimed
Comparative evaluation showing that xG improves Dixon-Coles or 1X2 predictions. That requires a real historical xG source wired through the Stage 1 store.

Stage 4 feature layer is complete.
