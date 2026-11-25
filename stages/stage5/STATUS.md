# Stage 5 — Player intelligence, injuries and suspensions

**Status (24 Nov 2026): BLOCKED (data).** The calculators below are tested scaffolding and are not used by the champion. No source was found with a licence permitting storage and model training, continuous PL coverage, and per-record availability timestamps. The findings and the requirements to unblock are in `docs/DATA_SOURCES_AND_LICENSING.md`.

## Scaffolding: feature layer (tested in isolation)

### Implemented and tested
- Injuries for a team (leakage-safe via as_of)
- Suspensions for a team
- Confirmed lineup lookup (only after available_at)
- Position-aware impact stub (goalkeeper > winger, etc.)
- Aggregate unavailable-player impact

### Tests
- `tests/test_stage5_players.py` — **6 passed**

### Not yet claimed
- Real player-quality model trained on minutes/xG/etc.
- Comparative backtest showing injury intelligence improves predictions
- Integration with live injury feeds

Stage 5 is blocked on data; the scaffolding is not a completed stage.
