# ALEA 3.0 Phase 2 Report — Recent Form Challenger

**Branch:** `dev/alea-3.0`  
**Date:** 2026-11-27  
**Champion (unchanged):** `alea-dc-v2.4.1`  
**SHA-256:** `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`

## What was implemented

### Variables (leakage-safe, before match date only)
- Last 5 / last 10: points per game, goals for/against, goal difference
- Venue splits: home-only form for home team, away-only form for away team
- Differentials: home form minus away form

### Model
- Multinomial logistic regression on the form feature vector
- L2 regularisation (reg=1.0)
- Retrained each walk-forward fold on matches strictly before the cutoff

### Infrastructure
- `experiments/alea30/form_features.py` — reference implementation + unit tests
- `experiments/alea30/form_features_fast.py` — indexed history for speed
- `experiments/alea30/form_model.py` — multinomial logit + walk-forward
- `experiments/alea30/run_phase2.py` — paired comparison vs champion

## Evaluation protocol
- Data: OpenFootball 2019-20…2025-26 (CC0), 2 660 matches
- Min train: 380; step: 56 days; 12 folds; **760** OOS matches
- Identical cutoffs for champion and form challenger
- ISO-week block bootstrap, 1000 resamples

## Results

| Model | Log loss | Brier | RPS | Accuracy |
|-------|----------|-------|-----|----------|
| **Champion Dixon-Coles** | **0.9951** | **0.5910** | **0.2084** | **0.518** |
| Form multinomial logit | 1.0263 | 0.6151 | 0.2204 | 0.501 |

**Paired difference (form − champion):** +0.0312 log loss  
**95% CI:** [+0.0086, +0.0530] → **champion significantly better**

## Decision
- Form-only multinomial logit is **not** competitive with Dixon-Coles.
- Do **not** promote.
- Form features remain useful as *inputs* for future ensembles or DC extensions, but a form-only probability model is rejected on this evidence.

## Blockers (unchanged)
- **xG (Phase 3 / Stage 4):** no licensed timestamped source in the store.
- **Player availability (Phase 5 / Stage 5):** blocked on licensing.
- **Context (Stage 6):** scaffolding only.

## Reproduction
```bash
python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26
# export CSV from Stage 1 store → data/openfootball_matches.csv
python -m experiments.alea30.run_phase2 --max-folds 12 --step-days 56 \
  --out results/alea30/phase2_report.json
python -m pytest tests/experiments/test_alea30_form.py -q
```

## Next
- Phase 4: expand Elo comparative backtest (Stage 3 Elo already exists).
- Phase 6: only consider ensemble if an independent component beats or ties the champion under uncertainty.
- Keep production forecasts on v2.4.1.
