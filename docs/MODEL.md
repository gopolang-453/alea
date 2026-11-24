# The model and the metrics

## Champion: `alea-dc-v2.4.1` (frozen, `alea_predictor_v2_4_1.py`)

The champion is a Dixon–Coles bivariate Poisson model with time decay and ridge shrinkage. In a match between home team \(i\) and away team \(j\):

\[
\lambda = \exp(\alpha_i + \delta_j + h), \qquad \mu = \exp(\alpha_j + \delta_i)
\]

- \(\alpha\) is attack strength. It is centred to mean 0 for identifiability.
- \(\delta\) is the defensive weakness, i.e. the goals-conceded propensity. Its mean is the league goal level.
- \(h\) is home advantage.

The scoreline probability is

\[
P(X=x, Y=y) = \tau(x,y;\lambda,\mu,\rho)\,\mathrm{Pois}(x;\lambda)\,\mathrm{Pois}(y;\mu)
\]

with the low-score correction

\[
\tau(0,0)=1-\lambda\mu\rho, \quad \tau(0,1)=1+\lambda\rho, \quad \tau(1,0)=1+\mu\rho, \quad \tau(1,1)=1-\rho,
\]

and \(\tau = 1\) otherwise. \(\rho\) is constrained to the interval that keeps every \(\tau > 0\) for every possible pairing, and \(|\rho| \le 0.3\).

### Fitting

The fit minimises the penalised, time-weighted negative log-likelihood

\[
-\sum_m w_m \log P(x_m, y_m) + r\Big(\sum_i \alpha_i^2 + \sum_i (\delta_i-\bar\delta)^2\Big), \qquad w_m = e^{-\xi\,\Delta t_m}
\]

where \(\Delta t_m\) is the age of match \(m\) in days.

- **Frozen parameters:** \(\xi = 0.0018\) per day (half-life about 385 days) and \(r = 1.0\).
- **Why they stay fixed:** per-fold tuning was significantly worse (see the consolidated report), so these values are not re-tuned.
- **Training data:** the model is refit before every scheduled run on all results available before the run time. Same-day rows are excluded by the model itself.
- **1X2 output:** exact market probabilities from the full distribution. These are not truncated at the scoreline grid.

## Registered challengers (prospective only; `config/model_registry.json`)

- `elo_ordered_logit`: Elo with initial rating 1500, K 20 and home advantage 50, fed into an ordered logit on the Elo difference.
- `dc_elo_equal_average`: the champion and Elo-OL probabilities averaged 50/50.

## Metrics

For outcome \(k \in \{H, D, A\}\), forecast \(p\) and one-hot \(o\):

- Log-loss: \(-\log p_k\).
- Brier: \(\sum_c (p_c - o_c)^2\), a 3-class sum in the range 0–2.
- RPS: \(\tfrac12 \sum_{c=1}^{2} (P_c - O_c)^2\), where \(P\) and \(O\) are cumulative over the order H, D, A.
- Accuracy: whether \(\arg\max p\) is the observed outcome.

All uncertainty uses a block bootstrap: ISO calendar weeks are resampled with replacement, 2,000 times with a fixed seed. Matches in the same week share conditions, so they are not independent.

Comparisons are always paired, meaning they use identical fixtures and identical training cutoffs.

## Reproducing the backtests

| Result | Command | Output |
|---|---|---|
| Walk-forward + 2025-26 holdout | `python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26` then `python scripts/run_stage9_mle_backtest.py --holdout-season 2025-26 --step-days 7` | `results/stage9_mle/` |
| 8 pre-registered challengers | `python scripts/run_stage9_candidate_evaluation.py` | `results/stage9_candidates/` |
| Tuned vs fixed, dev vs champion | `python scripts/compare_stage9_runs.py ...` (see the consolidated report) | `results/stage9_tuning_vs_fixed/`, `results/stage9_dev_vs_v241*/` |
| Champion vs closing market | `python scripts/compare_vs_market.py` (needs the local odds file) | `results/stage9_market/` (aggregates only) |
| Prospective evaluation | `python scripts/run_prospective_forecast.py ...` | `report.md`, `evaluation.json` next to the ledger |
