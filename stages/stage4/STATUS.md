# Stage 4 — Expected goals (xG)

**Status (24 Nov 2026): BLOCKED (data).** The calculators below are tested scaffolding and are not used by the champion. No source was found with a licence permitting storage and model training, continuous PL coverage, and per-record availability timestamps. The findings and the requirements to unblock are in `docs/DATA_SOURCES_AND_LICENSING.md`.

## Scaffolding: feature calculators (tested in isolation)

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

Stage 4 is blocked on data; the scaffolding is not a completed stage.
