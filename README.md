# ALEA

A Dixon–Coles Poisson model for Premier League home / draw / away probabilities.

This is a forecasting prototype. It is not a betting system. Staking is off. A positive expected value in the value engine is not an edge.

## What is in this repository

| Path | What it is |
|---|---|
| `alea_predictor_v2_4_1.py` | Frozen baseline. Do not edit it. SHA-256 `4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a` |
| `alea_value_engine_v0_2_1.py` | Compares model probabilities with decimal odds. Does not place bets. |
| `frozen/alea_predictor_v2_3_1.py` | Older frozen baseline. |
| `tests/` | The v2.4.1 test suite. Run it from this directory. |
| `dev/alea_predictor_dev.py` | Unreleased repair. Version string `alea-dc-dev`. Refuses `reg = 0` when a team has scored or conceded no goals. |
| `FULL_AUDIT.md`, `DEV_REPORT.md` | What was tested and what failed. |
| `results/` | The blind walk-forward predictions and the score file. |

## Install

```bash
pip install -r requirements.txt
```

`mpmath` is only needed for `tests/test_15_exact_score_probabilities.py`.

## Run the tests

```bash
python tests/run_all.py
python dev/tests/test_dev_repairs.py
```

## Train and predict

```python
import alea_predictor_v2_4_1 as alea

data = alea.load_from_csv(seasons=("2425", "2526"))
params = alea.fit_model(data, xi=0.0, reg=1.0, live=True)
print(alea.predict(params, "Arsenal", "Chelsea"))
```

Historical files came from [football-data.co.uk](https://www.football-data.co.uk/). They are not bundled here. The scored predictions are in `results/`.

## What the tests showed

On 1,140 held-out matches, with training strictly before each match day:

| | Log loss | Brier | Right result |
|---|---:|---:|---:|
| v2.4.1 | 0.996 | 0.588 | 0.518 |
| Development candidate | 0.987 | 0.588 | 0.519 |
| Bet365 closing, margin removed | 0.960 | 0.570 | 0.550 |

The development candidate's log-loss gap versus v2.4.1 is one match (Burnley 2–0 Sunderland, 23 August 2025), where v2.4.1 produced a probability of about 10⁻⁷. On the other 1,139 matches the scores are the same. Neither model matches the closing price. The value engine's 2% edge rule lost about 12% per unit on early prices. Do not bet from it.


---

## ALEA 3.0 repair track

The active engineering repair plan and acceptance gates are documented in
[REPAIR_PLAN.md](REPAIR_PLAN.md). Stage 13 remains open until real-data
walk-forward evidence, integration and release checks pass.

### Development setup

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/security_check.py
```

### Historical results and production Dixon–Coles evaluation

The repair track uses OpenFootball's CC0 historical results as an initial
results-only source. It does not provide historical xG, injuries, lineups or a
guaranteed live feed. Raw data and the SQLite database are stored locally and
are not committed to Git.

```bash
python scripts/fetch_openfootball.py
python scripts/run_stage9_mle_backtest.py --holdout-season 2023-24 --step-days 56
```

The walk-forward runner uses the production v2.4.1 Dixon–Coles MLE, keeps
calendar dates together, filters training results by their actual availability
timestamp, uses expanding training windows, fits temperature calibration on
development predictions only, and reports a separate final-season holdout with
paired ISO-week bootstrap uncertainty. It does not tune hyperparameters on the holdout.
A failed fit aborts the run; it is not silently skipped.

**Important:** passing unit tests does not mean ALEA 3.0 is released. Do not
promote a candidate or enable betting automation without the evidence gates in
the repair plan.
