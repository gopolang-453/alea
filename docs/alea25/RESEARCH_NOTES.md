# ALEA 2.5 – Research Notes (Mathematical Engine & Calibration)

Generated as part of the ALEA 2.5 milestone. All recommendations are experimental; the frozen champion `alea-dc-v2.4.1` remains the production baseline.

## 1. Dixon–Coles time-decay

**Primary reference**  
Dixon, M.J. & Coles, S.G. (1997). Modelling Association Football Scores and Inefficiencies in the Football Betting Market. *Journal of the Royal Statistical Society: Series C*, 46(2), 265–280.  
https://doi.org/10.1111/1467-9876.00065

The original paper used a relatively strong exponential decay. Subsequent practical implementations (including the ALEA champion) have settled on milder values (ξ ≈ 0.0018 ≈ 385-day half-life) because Premier League team strengths change slowly within a season and because aggressive decay amplifies estimation noise for newly promoted sides.

**ALEA 2.5 experiment**  
A discrete grid around the champion value (0.0008 … 0.0050) is evaluated under the same walk-forward protocol. The goal is to quantify sensitivity, not to auto-tune on every fold (previous Stage-9 work showed per-fold retuning degraded hold-out performance).

## 2. Regularisation / shrinkage

Attack and defence parameters for teams with few matches are high-variance. L2 penalties of the form used in the champion (`reg * (‖α‖² + ‖δ − δ̄‖²)`) are standard. The champion uses `reg = 1.0`. ALEA 2.5 explores {0.25, 0.5, 1.0, 2.0, 4.0} while keeping the functional form identical so that differences are attributable only to the strength of shrinkage.

## 3. Temperature scaling

**Reference**  
Guo, C., Pleiss, G., Sun, Y. & Weinberger, K.Q. (2017). On Calibration of Modern Neural Networks. *ICML*.  
https://arxiv.org/abs/1706.04599

Temperature scaling is a single-parameter post-hoc method that preserves ranking while improving calibration. Stage 8 already implements a leakage-aware version; ALEA 2.5 re-uses it and adds reliability diagrams and an optional isotonic baseline for comparison.

**Important constraint**  
Calibration parameters may only be fitted on predictions whose training cutoff is strictly before the match date. This rule is enforced in both Stage 8 and the new `experiments.alea25.calibration_ext` module.

## 4. Isotonic regression

Isotonic regression can achieve lower calibration error than temperature scaling when the reliability curve is non-monotonic, but it is more data-hungry and can over-fit on small samples. ALEA 2.5 therefore gates isotonic behind a minimum-sample threshold (default 200) and still requires chronological integrity.

## 5. Block bootstrap

Matches in the same ISO week are not independent. ALEA already uses ISO-week block bootstrap for promotion decisions (see `config/model_registry.json`). The 2.5 utilities expose the same procedure for any paired loss series so that experimental candidates can be judged under the identical uncertainty model.

## 6. What is deliberately *not* done

- No xG, injury or lineup features (still blocked by licensing / timestamp requirements – see `docs/DATA_SOURCES_AND_LICENSING.md`).
- No automatic promotion.
- No modification of the prospective ledger or the frozen champion source.
- No rewriting of Git history.

## 7. Next measurements required

1. Full walk-forward on the OpenFootball 2019-20 … 2025-26 store for every grid point.
2. Extraction of out-of-sample 1X2 probability vectors from those folds for the calibration suite.
3. Paired block-bootstrap CIs on the real data (n ≥ 300 preferred before any promotion discussion).

Until those numbers exist, no experimental model may be described as “better than the champion”.
