> **Superseded (24 Nov 2026):** see [ALEA_3.0_STATUS_REPORT_2026-11-24.md](ALEA_3.0_STATUS_REPORT_2026-11-24.md) for current, re-measured status. Kept for history only.

# ALEA 3.0 Test Results — Stage 10 reconciliation

**Branch:** `repair/alea-3.0-claude-verified`  
**Date:** 2026-11-21  
**Environment:** local Python 3.12, pytest 9.0.3  
**Data:** SYNTHETIC only

## Command

```bash
PYTHONPATH=. python -m pytest tests/test_stage10_champion_comparison.py -v --tb=line
```

## Result

```
12 passed in 1.09s
```

### Individual outcomes

| Test | Result |
|------|--------|
| test_register_and_verify | PASSED |
| test_promote_rejects_missing_metrics | PASSED |
| test_promote_rejects_too_few_samples | PASSED |
| test_promote_rejects_when_ci_includes_zero | PASSED |
| test_promote_rejects_when_worse_than_champion_baseline | PASSED |
| test_promote_rejects_wrong_baseline_version | PASSED |
| test_promote_rejects_tampered_artifact | PASSED |
| test_valid_promotion_succeeds | PASSED |
| test_rollback_restores_previous | PASSED |
| test_head_to_head_result_gate_logic | PASSED |
| test_comparison_rejects_insufficient_fixtures | PASSED |
| test_failed_register_does_not_create_champion | PASSED |

**No real EPL validation was performed.** These tests prove the registry gates and comparison fail-closed behaviour only.
