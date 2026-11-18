# Stage 5 — Player intelligence, injuries and suspensions

## Status: FEATURE LAYER COMPLETE AND TESTED

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

Stage 5 feature contracts are complete and tested.
