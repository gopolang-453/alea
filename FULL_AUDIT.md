# ALEA full audit — 12 November 2026

This is a development audit. Nothing here is a release. Original v2.4.1 was not edited. Its SHA-256 is still

`4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`

There is no untouched season left inside 2022/23–2025/26. Every number below that uses those matches is an explanation of this sample, not an independent pass. The next season is the first clean test.

## Recommendation

Do not assign a version number.

The development file stops probabilities of 10⁻⁷. That is a real defect repaired. The log-loss change on the 1,140 matches is not conclusive, Brier did not improve, and Bet365 is still better. The value engine, pointed at the model's own "edges", loses money. That loss is distinguishable from zero. It is not a betting system.

## Problems, in order

| # | Problem | Status |
|---|---|---|
| 1 | `reg = 0` makes the Poisson rating unbounded when a team has scored or conceded nothing. Three matches got probabilities below 0.001. | Repaired in `alea_predictor_dev.py` only. v2.4.1 still has it. |
| 2 | On the same 1,140 matches the repaired model is still worse than Bet365 closing prices. Gap in log loss +0.027, 95% interval +0.015 to +0.038. | Not repaired. Goals history does not contain what the price contains. |
| 3 | The value engine's 2% edge rule, using v2.4.1 probabilities and Bet365 early odds, lost 11.9% per unit. 1,046 bets. 95% interval −21.2% to −2.1%. | The arithmetic is correct. The probabilities are not an edge. Staking stays off. |
| 4 | Draws rose from 21.6% to 27.4%. The model went from 21.0% to 24.2%. | No adjustment added. A temperature fitted only on past matches did not help. |
| 5 | The football API function raises `NotImplementedError`. There is no key and no response schema. | Left unimplemented. CSV loading works. |
| 6 | Early-odds timing is an assumption (Friday for Saturday/Sunday, Tuesday for midweek). The file has a clock but no timezone and no proof of when Bet365 posted the price. | Not verified. Closing prices were not used as model inputs. |
| 7 | `Man United` was not aliased. In this file every row used that spelling, so it was one club, not two. | Aliased in the development copy only. |

Things that were checked and are not broken:

- 1,520 matches, 380 in each season, no duplicate fixtures, no negative scores, no team playing itself.
- Walk-forward training dates are strictly before the test dates.
- Shin de-vig probabilities sum to 1. They differ from proportional de-vig by 0.006 on average. Log loss of the two market probabilities differs by 0.0004. Both are acceptable. The value engine uses proportional, and it says so. The backtest comparison uses Shin.
- A full-sample fit at `reg = 1` has attack strengths between −0.51 and +0.43. The 3-log-point rejection is about six times larger than any real rating in this league. It does not bind on a normal fit. It exists to stop the −12 failure.
- Dixon–Coles low-score factors stay positive. On the full sample the smallest correction factor was 0.66. Rho was −0.084.
- One Arsenal–Chelsea prediction from that fit: home/draw/away sum to 1. The score-grid tail is 3.5×10⁻¹⁰.
- Save and load round-trip. The development version string is `alea-dc-dev`, so it cannot be loaded as v2.4.1.
- Odds of 1.00 are rejected. A 50% probability at 2.10 is reported as +5% expected return, and staking stays off.

## What was measured and not added

All of these used only information from earlier matches. None is in the development model.

| Candidate | Result |
|---|---|
| Freeze `xi = 0`, `reg = 3` from 2022/23 | Log loss looked slightly better. The interval included zero. Not adopted. |
| Rest days, one coefficient | Slightly worse. Not adopted. |
| Temperature on the three probabilities | Mean temperature 1.01. Slightly worse. Not adopted. |
| Past shots on target (difference of rates, at least 5 earlier matches) | 865 later matches. Log loss 1.000 with the feature, 0.999 without. Not adopted. |

Not in the files at all, so not tested: expected goals, lineups, injuries, suspensions, Elo, transfers, managers. Shots, shots on target, corners and cards are in the file, but only after the match. They can be used for the next match. The shots-on-target test above is that test. It did not help.

## Bookmaker comparison

Closing prices, Shin de-vig, model trained only on earlier dates. 1,140 matches.

| | Log loss | Brier | RPS | Right result |
|---|---:|---:|---:|---:|
| v2.4.1 | 0.996 | 0.588 | 0.202 | 0.518 |
| Development candidate | 0.987 | 0.588 | 0.202 | 0.519 |
| Bet365 close | 0.960 | 0.570 | 0.194 | 0.550 |

Development minus v2.4.1 log loss: −0.010, interval −0.033 to +0.003, includes zero.

The gap is not one season and not one result type. It is largest when the two disagree on the winner (150 matches, market right about twice as often) and on home wins. Away results are not where the model loses. Promoted teams and one-match teams are worse, and the three exploded probabilities were part of that. Removing them does not close the rest of the gap.

## Value engine

Run on the early-odds file, which was built with the model trained only up to the assumed odds date. v2.4.1 probabilities. Proportional de-vig. Flat 1 unit. No commission subtracted, so the true loss would be larger.

| Rule | Bets | ROI | 95% interval | Drawdown |
|---|---:|---:|---|---:|
| EV > 2% and edge > 2 points | 1,046 | −11.9% | −21.2% to −2.1% | 138 units |
| Any positive EV | 1,244 | −11.8% | −20.1% to −3.3% | 158 units |
| EV > 5% and edge > 5 points | 614 | −15.2% | −26.4% to −3.4% | 101 units |
| Bet the shortest price every match | 1,140 | −4.8% | — | — |

The model's selections lose more than blindly betting the favourite. Home and away "edges" lose. Draw selections were slightly positive in this sample (+7% on 209 bets) and that slice was not tested on its own as a strategy, because it was noticed after looking at the results. Long prices (over 5.0) were the worst band: −24.7% on 255 bets.

This is not evidence of a profitable draw system. It is evidence that the filter does not find an edge.

## Tests actually run

- `tests/test_dev_repairs.py` — re-run after the Shin and EV checks were added. See the log from this session.
- v2.4.1 `tests/run_all.py` — 16 of 16 passed. Log: `v241_suite_log.txt`. That suite tests the untouched file.
- Closing backtest of the development candidate — `closing_summary.json`, 487 seconds, 1,140 matches.
- Early-odds value-engine backtest — numbers in this file, computed in this session.
- Shots-on-target expanding window — this session.
- Temperature scaling — the previous session.

Not run, because the columns or the feed do not exist: xG, lineups, injuries, a live API.

## Roadmap

1. Leave v2.4.1 as the reference. Leave `alea-dc-dev` as the candidate that cannot emit a 10⁻⁷ probability.
2. Do not retune `xi`, `reg`, the 3-log-point gate, or a calibration on these 1,140 matches again.
3. Score both models on the next Premier League season as it is played, with the same date rule, before looking at which one won.
4. Do not turn the value engine on. A negative interval that excludes zero is a failed strategy, not a small sample.
5. A feature is only worth a model change if it beats the development candidate on matches that were not used to invent it. Shots on target, rest days and a temperature already failed that test inside this sample.
