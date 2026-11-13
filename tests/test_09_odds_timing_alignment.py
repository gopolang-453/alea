"""TEST 09 - odds-timing-aware market comparison.
Problem (v2.3.1): the model was trained on every result up to the fold cutoff and compared with odds that were
observed EARLIER (Football-Data's early odds are taken Friday afternoon for weekend games, Tuesday for midweek),
and market metrics were computed only on matches that had odds while model metrics used all matches.
Fix (v2.4): aligned_market_backtest trains, for each odds-observation date D, only on results dated before D,
and scores model and market on exactly the same matches, with paired bootstrap intervals.
Checks: (a) the weekday rule, (b) the alignment guarantee on every fold, (c) how many comparisons an
unaligned walk-forward would have leaked, (d) the machinery gives the RIGHT SIGN when the answer is known."""
import _paths
import numpy as np, pandas as pd
import alea_predictor_v2_4_1 as a
from _common import make_matchday_league

# (a) weekday rule
exp = {"2026-11-06": "2026-11-06", "2026-11-07": "2026-11-06", "2026-11-08": "2026-11-06", "2026-11-09": "2026-11-06",
       "2026-11-10": "2026-11-10", "2026-11-11": "2026-11-10", "2026-11-12": "2026-11-10"}
for d, e in exp.items():
    got = str(a.odds_information_date(d).date()); assert got == e, (d, got, e)
assert str(a.odds_information_date("2026-11-08", "kickoff_day").date()) == "2026-11-08"
try: a.odds_information_date("2026-11-08", "nonsense"); raise SystemExit("FAIL")
except ValueError: pass
print("a) Sat/Sun/Mon -> preceding Friday, Fri -> same day, Tue/Wed/Thu -> Tuesday; closing odds -> match day")

# (b)+(c) alignment guarantee, and how much an unaligned procedure would leak
df, teams, att, dfn = make_matchday_league(21, n_weeks=70, with_odds=True, reschedule_prob=0.10)
day = df.Date.dt.normalize(); info = day.map(a.odds_information_date)
un, *_ = a.walk_forward_backtest(df, min_train_matches=300, step_days=14, verbose=False, tune_each_fold=False)
leaked = tot = 0
for f in un["fold_log"]:
    blk = df[(day >= pd.Timestamp(f["cutoff"])) & (day <= pd.Timestamp(f["test_max_date"]))]
    in_fold = blk[blk.Date >= pd.Timestamp(f["test_min_date"])]
    for r in in_fold.itertuples():
        tot += 1
        leaked += pd.Timestamp(f["train_max_date"]) >= info[r.Index]       # training includes results from on/after the odds date
print(f"c) a date-grouped but UNALIGNED backtest would compare {leaked}/{tot} matches ({leaked/tot:.0%}) against odds that were "
      f"observed before some of the training results existed")
assert leaked > 0
rep, mp, kp, out = a.aligned_market_backtest(df, min_train_matches=300, retune_every=10**6, verbose=False, n_boot=1000)
viol = [f for f in rep["fold_log"] if not pd.Timestamp(f["train_max_date"]) < pd.Timestamp(f["info_date"])]
print(f"b) aligned backtest: {rep['n_folds']} folds, {len(viol)} violate 'train only on results dated before the odds date'; {rep['n_matches_scored']} matches scored")
assert not viol and rep["n_matches_scored"] > 300
for f in rep["fold_log"][:2]: print("   e.g.", f)
# model and market scored on the SAME matches
assert len(mp) == len(kp) == len(out) == rep["n_matches_scored"]

# (d) sign tests with a KNOWN answer
d = rep["model_minus_market_log_loss"]
print(f"d1) market = the TRUE probabilities (+5% margin): model - market log loss = {d['mean']:+.4f} "
      f"[{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]  -> {rep['verdict_log_loss']}")
assert d["mean"] > 0                       # nobody can beat the truth; the model can only be equal or worse
noisy, *_ = make_matchday_league(22, n_weeks=70, with_odds=True, market="noisy", noise=0.8, reschedule_prob=0.10)
rep2, *_ = a.aligned_market_backtest(noisy, min_train_matches=300, retune_every=10**6, verbose=False, n_boot=1000)
d2 = rep2["model_minus_market_log_loss"]
print(f"d2) market = truth + noise (a clearly BAD market): model - market log loss = {d2['mean']:+.4f} "
      f"[{d2['ci_low']:+.4f}, {d2['ci_high']:+.4f}]  -> {rep2['verdict_log_loss']}")
assert d2["mean"] < 0 and not d2["includes_zero"]
# (the same machinery said 'not distinguishable' for a mildly noisy market (noise 0.35) on this ~390-match sample -
#  that is the honest answer at this sample size, which is exactly why intervals are reported)
# odds missing/invalid are handled, closing-odds columns work with the kickoff-day rule
c = noisy.rename(columns={"B365H": "B365CH", "B365D": "B365CD", "B365A": "B365CA"})
c.loc[c.index[:40], "B365CH"] = np.nan
rep3, *_ = a.aligned_market_backtest(c, odds_columns=("B365CH", "B365CD", "B365CA"), rule="kickoff_day",
                                     min_train_matches=300, retune_every=10**6, verbose=False, n_boot=300)
assert rep3["rule"] == "kickoff_day" and rep3["n_matches_scored"] > 200
try: a.aligned_market_backtest(df.drop(columns=["B365H"]), verbose=False); raise SystemExit("FAIL")
except ValueError: pass
print("PASS")
