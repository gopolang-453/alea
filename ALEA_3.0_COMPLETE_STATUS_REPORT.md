> **Superseded (24 Nov 2026):** see [ALEA_3.0_STATUS_REPORT_2026-11-24.md](ALEA_3.0_STATUS_REPORT_2026-11-24.md) for current, re-measured status. Kept for history only.

# ALEA 3.0 — Complete Status Report
**Date:** 18 November 2026  
**Repository:** gopolang-453/alea  
**Prepared for review**

---

## 1. Executive summary

Stages 0–12 have tested contracts, scaffolding, and (where data allowed) real-data evidence.  
**Stage 13 (final acceptance / ALEA 3.0 release) is NOT complete.**

No stage was marked fully passed without green unit tests or a documented evidence gap. Comparative walk-forward results exist for the baseline, Elo, and recent form. xG, injuries, lineups, and contextual features were not scored because real historical sources for them were not wired.

---

## 2. Stage-by-stage status

| Stage | Title | Status | Tests / evidence |
|-------|--------|--------|------------------|
| 0 | Audit existing ALEA | Complete | Manual inspection of repo |
| 1 | Data collection & management | Core complete | 13 unit tests passed; real CSV ingest works |
| 2 | Dixon-Coles mathematics | Complete | 9 unit tests passed |
| 3 | Team strength, form, ratings | Feature layer complete | 8 unit tests passed; Elo + form scored on real data |
| 4 | Expected goals (xG) | Feature layer complete | 5 unit tests passed; not scored (no historical xG source) |
| 5 | Player intelligence / injuries | Feature layer complete | 6 unit tests passed; not scored (no historical injury source) |
| 6 | Contextual factors | Feature contracts complete | 4 unit tests passed; not scored (no historical source) |
| 7 | ML and ensemble | Contracts complete | 7 unit tests passed; no models trained |
| 8 | Probability calibration | Applied on real predictions | Temperature scaling; best T=1.1, negligible gain |
| 9 | Historical backtesting | Core complete (9.1–9.4) | See section 3 |
| 10 | Automation | Partial | CSV updater idempotent; no live API scheduler |
| 11 | Prediction interface | Contracts + sample | Sample explanation generated from real prediction |
| 12 | Reliability | Contracts + secrets scan | No hardcoded API keys in stage code |
| 13 | Final acceptance | **NOT COMPLETE** | See section 5 |

**Unit tests across Stages 1–12: 63 passed** (from earlier sitting).

---

## 3. Stage 9 — Real-data backtest results

**Data:** 5 Premier League seasons (2019/20–2023/24), 1,900 matches from football-data.co.uk.  
**Protocol:** Expanding window, min_train=300, step=50 → 1,600 out-of-sample predictions. Leakage-safe (train only on earlier matches). Reproducible on second run.

### 9.1 Data import — PASS
- 1,900 records imported
- Second import of the same files added 0 rows
- Snapshot retrieves all 1,900
- Scores ≥ 0, teams present, no duplicate fixture keys

### 9.2 Walk-forward — PASS
- Training cutoff strictly before each test block
- Identical probabilities on a second run
- Probabilities sum to 1

### 9.3 Baseline (attack/defence rates + Stage 2 score matrix)

| Metric | Value |
|--------|-------|
| n | 1,600 |
| Log loss | 1.057 |
| Brier | 0.635 |
| 1X2 accuracy | 0.468 |

### 9.4 Individual feature checks (same 1,600 matches)

| Model | Log loss | Brier | Accuracy | vs baseline |
|-------|----------|-------|----------|-------------|
| Baseline (rates) | 1.057 | 0.635 | 0.468 | — |
| Elo (Stage 3, fixed 0.25 draw) | 0.984 | 0.585 | 0.536 | Better |
| Recent form (Stage 3, last-5 PPG) | 1.031 | 0.619 | 0.491 | Better |

**Notes**
- Elo and form both improve on this sample. Elo is stronger.
- Conversions are crude (fixed draw probability). Directional evidence only.
- xG, injuries, suspensions, lineups, and contextual features were **not scored** — no real historical sources were connected.
- Bookmaker de-vig comparison was not run (odds columns exist in the CSVs but were not scored).

### 9.5 Combined model — OPEN
Not run as a full combined system. Only Elo and form showed improvement. A proper combined evaluation needs the same protocol on all retained features plus a held-out period. Left open until more feature sources exist.

---

## 4. Stage 8 — Calibration

Applied temperature scaling to the 1,600 baseline predictions.

| Temperature | Log loss |
|-------------|----------|
| 0.8 | 1.061 |
| 0.9 | 1.058 |
| 1.0 | 1.057 |
| **1.1** | **1.0572** |
| 1.2 | 1.058 |
| 1.5 | 1.061 |

Best T=1.1 gives a negligible improvement. Calibration gap did not improve. Not a meaningful gain on this baseline. Not used as a final model change.

---

## 5. Stage 13 — Why it is not complete

Stage 13 is the acceptance gate, not a feature stage. It stays open because:

1. **No full production Dixon-Coles MLE walk-forward.** The Stage 9 run used a fast rates model + Stage 2 score matrix. The production `alea_predictor_v2_4_1.py` MLE was too slow for a full multi-fold run in this sitting.
2. **xG, injuries, lineups, and contextual features not evaluated on real data.** Feature contracts exist and are unit-tested, but no historical source was wired, so they cannot be retained or rejected on evidence.
3. **No live/scheduled fixture or results API updater.** Stage 10 CSV updater is idempotent on local files; there is no daemon or live feed.
4. **No trained LightGBM/XGBoost.** Intentionally not forced. Simpler models were kept where they performed.
5. **No deployed interface or monitoring.** Stage 11–12 contracts exist; there is no running service.
6. **Combined model (9.5) not run.** Only Elo and form were scored.
7. **Calibration gain is negligible.** Not adopted.

---

## 6. Recommended next steps

1. Wire one additional real source (xG or injuries) through the Stage 1 store with realistic `available_at` timestamps.
2. Re-run the Stage 9 walk-forward with that feature under the same protocol.
3. Keep the feature only if log loss / Brier improve on matches not used to invent it.
4. Connect a scheduled results updater (Stage 10) once a stable free feed is chosen.
5. Only then reconsider Stage 13.

---

## 7. Bottom line

**ALEA 3.0 is not released.**

The mathematical foundation (Stage 2), data contracts (Stage 1), and Stage 9 core backtest on 1,900 real Premier League matches are in place and tested. Elo and form show directional improvement. Everything else required for final acceptance (additional feature evidence, live automation, deployed product) remains open.

A checklist tick is not proof. Stage 13 stays open until the evidence gaps above are closed.


---

## Repository reproducibility update — 18 November 2026

A later repository audit found that the 1,900-match historical run described below is **not reproducible from the committed checkout**: the referenced five-season CSV files and the persistent-store module originally imported by the Stage 9.1 test were absent. The earlier metrics should therefore be treated as reported experiment results, not independently verified release evidence.

The repository now includes:
- SQLite-backed `PersistentDataStore` and validated `ingest_csv` in `stages/stage1/data_store.py`.
- Idempotent duplicate handling and rejection of conflicting source records.
- A conservative date-only availability fallback (36 hours after midnight UTC on the match date); this is a safety delay, not the provider's exact publication timestamp.
- Stage 1 regression tests and a Stage 9.1 CSV-ingestion smoke test using a small synthetic fixture.
- GitHub Actions run [44297685638](https://github.com/gopolang-453/alea/actions/runs/44297685638), which passed **8 tests** on commit `01b8a5d8890ff0cb66b3ec1998b898d105a25559`.

This smoke test does **not** reproduce the 1,900-match dataset or the 1,600-prediction backtest. The production Dixon–Coles MLE walk-forward and Stage 9.5 combined-model evaluation remain open. Stage 13 remains NOT COMPLETE.
