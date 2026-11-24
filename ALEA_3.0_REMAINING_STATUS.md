> **Superseded (24 Nov 2026):** see [ALEA_3.0_STATUS_REPORT_2026-11-24.md](ALEA_3.0_STATUS_REPORT_2026-11-24.md) for current, re-measured status. Kept for history only.

# ALEA 3.0 — Remaining work status (after Stage 9–12 pass)
**Date:** 18 November 2026  
**For review**

## What was finished this sitting

| Step | Status | Evidence |
|------|--------|----------|
| 9.1 Real data import | PASS | 1,900 matches, second import adds 0 |
| 9.2 Walk-forward | PASS | Leakage-safe, reproducible |
| 9.3 Baseline | PASS | n=1600, log loss 1.057, Brier 0.635, acc 0.468 |
| 9.4 Elo check | Directional | Elo log loss 0.984 vs baseline 1.057 (crude draw) |
| 9.5 Combined | Open | Only Elo scored; other features lack sources |
| 8 Calibration | Applied | Best T=1.1, log loss 1.0572 (negligible gain) |
| 10 CSV updater | PASS | Idempotent on real CSVs (second run adds 0) |
| 11 Interface | PASS | Sample explanation generated from real prediction |
| 12 Secrets scan | PASS | No hardcoded API keys in stage code |
| 13 Final acceptance | **NOT COMPLETE** | See blockers below |

## Stage 13 blockers (unchanged in substance)

1. No full production Dixon-Coles MLE walk-forward (used fast rates model).
2. xG, injuries, lineups, contextual features not scored on real historical data (no sources wired).
3. No live/scheduled fixture or results API updater.
4. No trained LightGBM/XGBoost (intentionally not forced).
5. No deployed service or monitoring daemon.
6. Calibration gain is negligible on this baseline; not a meaningful improvement.

## Recommendation

Stage 13 should stay open until:
- A live or scheduled results feed is connected, and
- At least one additional feature (beyond the crude Elo) is evaluated under the same walk-forward protocol and either retained or explicitly rejected.

**ALEA 3.0 is not released.** Foundation and Stage 9 core are in place and tested. Evidence and production automation remain open.
