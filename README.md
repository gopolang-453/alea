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
| `dev/alea_predictor_dev.py` | Unreleased repair candidate, version string `alea-dc-dev`. Two guards not in v2.4.1: refuses `reg = 0` when a team has scored or conceded no goals (the unpenalised MLE is unbounded there), and refuses any fit where a team's attack/defence strength exceeds 3 log-points (~20x the league scoring rate) regardless of cause. This is a **robustness** fix, not a demonstrated accuracy improvement — see below. |
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

On 1,140 held-out matches (11 Aug 2023 – 24 May 2026), with training strictly before each match day. These numbers were independently recomputed from the raw per-match rows in `results/predictions_closing_odds.csv` and `results/predictions_closing_dev.csv` (not just taken from a summary file), and the raw data passed integrity checks: no duplicate fixtures, no missing/invalid odds, results agree with recorded goals, no odds-information date falls after its match date, and training-set size never shrinks across folds.

| | Log loss | Brier | Right result |
|---|---:|---:|---:|
| v2.4.1 | 0.9964 | 0.5876 | 51.8% |
| Development candidate | 0.9868 | 0.5881 | 51.9% |
| Bet365 closing, Shin de-vigged | 0.9595 | 0.5698 | 55.0% |

By season (log loss):

| Season | v2.4.1 | Dev | Market |
|---|---:|---:|---:|
| 2023–24 | 0.945 | 0.948 | 0.898 |
| 2024–25 | 0.976 | 0.981 | 0.968 |
| 2025–26 | 1.068 | 1.032 | 1.014 |

The market beats both models in every season, and the gap does not close over time.

**The development candidate is a robustness fix, not a demonstrated accuracy improvement.** Its entire log-loss advantage over v2.4.1 comes from one match: Burnley 2–0 Sunderland, 23 August 2025, where v2.4.1's unregularised fit assigned the actual result a probability of about 2.7×10⁻⁷ (market-implied: ~41%) and the dev candidate assigned it 9.9%. Excluding that single match, the dev candidate is marginally *worse* than v2.4.1 across the other 1,139 matches (mean log-loss difference +0.0016 — noise, not signal). Promote it for eliminating that failure mode, not because it predicts football better.

Neither model (nor the market) ever predicts "draw" as the single most likely outcome — that's normal for 1X2 forecasting, not a calibration failure. Checked separately, draw probabilities are reasonably well calibrated for both: in the 0.20–0.27 predicted-probability bucket (743 matches), the dev model's observed draw frequency was 25.8% against a predicted average of 23.6%; the market's calibration was similarly close across its bins.

Neither model matches the closing price. The value engine's 2% edge rule lost about 12% per unit on early prices. Do not bet from it.

## Limitations / not yet done

- Refitting either model from scratch, or testing genuinely new changes (different `xi`/`reg`, Elo ratings, xG, calibration layers), needs the training-period matches before 11 Aug 2023. Those aren't bundled in this repository — only the 1,140-match evaluation window is. See the data-acquisition checklist for what's needed.
- The `stages/` directory (xG, player, context, ensemble feature contracts) is unit-tested in isolation but not wired into either released predictor, and its own status notes say stage-level comparative evidence doesn't exist yet. Treat it as scaffolding, not a working pipeline.
