# Stage 1 — Data store acceptance

**Branch:** `repair/alea-3.0-end-to-end`  
**Date:** 19 November 2026

## Status: PASS (with documented limits)

Stage 1 is the persistent, idempotent, time-aware store used by later stages.

### What is accepted

| Requirement | Evidence |
|-------------|----------|
| SQLite persistence + reopen | `tests/test_stage1_persistent_store.py::test_import_is_idempotent_and_survives_reopen` |
| Idempotent identical import | same test + OpenFootball import test |
| Conflicting duplicate fails closed | `test_conflicting_duplicate_fails_closed` |
| Conservative next-day availability for date-only results | `test_date_only_result_is_not_available_on_match_day` |
| Atomic OpenFootball import (rollback on bad row) | `test_openfootball_season_import_rolls_back_on_bad_row` |
| Feature records coexist with results | `tests/test_stage1_persistent_features.py` |
| Feature kinds (xg, injury, weather) timestamped and idempotent | same |
| Timezone-aware cutoffs enforced | feature + result tests |
| Canonical team aliases | Burnley/Man Utd → manchester united |
| Schema version check | `PersistentDataStore.SCHEMA_VERSION = 1` |

### Explicit limits (not defects)

1. **No live kickoff timestamps** — OpenFootball (and most free historical sources) are date-only. Availability is deliberately conservative (next UTC day). This is correct policy, not a missing feature.
2. **No schema migrations beyond version 1** — Version mismatch fails closed. Future schema changes must land as a new version with an explicit upgrade path before any data migration is attempted.
3. **Feature sources remain external** — Stage 1 stores whatever is given to it. It does not invent xG, injuries or lineups. Stages 4–6 stay disabled for prediction until real timestamped sources exist.

### Commands that must pass

```bash
python -m pytest tests/test_stage1_persistent_store.py tests/test_stage1_persistent_features.py -q
```

### Decision

Stage 1 is accepted for use by Stages 2–13 on this branch.  
Do not reopen Stage 1 acceptance unless a new data source, schema change, or leakage bug is discovered.
