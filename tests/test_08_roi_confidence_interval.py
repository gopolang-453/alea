"""TEST 08 - ROI confidence intervals.
Checks that the interval is HONEST, using bets whose true ROI is known:
  a) coverage: a 95% interval contains the true ROI about 95% of the time
  b) no edge -> the interval includes zero about 95% of the time (the engine must say 'not distinguishable')
  c) clustering: two bets on the same match are NOT independent - the clustered interval must be wider
  d) sample size: how wide the interval still is at 1,000 / 3,000 / 10,000 bets"""
import random
import _paths
import alea_value_engine_v0_2_1 as v2

def simulate(rng, n, p, odds):
    return [odds - 1.0 if rng.random() < p else -1.0 for _ in range(n)]

rng = random.Random(1)
REPS, N, NB = 150, 100, 400
# a) coverage; odds 2.5, p=0.42 -> true ROI = 0.42*2.5 - 1 = +0.05
cover = sum(ci["ci_low"] <= 0.05 <= ci["ci_high"] for ci in
            (v2.roi_confidence_interval(simulate(rng, N, 0.42, 2.5), n_boot=NB, seed=s) for s in range(REPS)))
print(f"a) true ROI +5.0%: 95% interval contained it in {cover}/{REPS} = {cover/REPS:.1%} of simulated samples")
assert cover / REPS >= 0.88
# b) no edge (p=0.40 at odds 2.5 -> true ROI 0)
inc = sum(v2.roi_confidence_interval(simulate(rng, N, 0.40, 2.5), n_boot=NB, seed=s)["includes_zero"] for s in range(REPS))
print(f"b) true ROI 0.0%: interval included zero in {inc}/{REPS} = {inc/REPS:.1%} of samples")
assert inc / REPS >= 0.88
# c) clustering: every match has two perfectly correlated bets (e.g. Over 2.5 and BTTS both won/lost together)
base = simulate(rng, 150, 0.42, 2.5)
paired = [x for x in base for _ in range(2)]; ids = [i for i in range(len(base)) for _ in range(2)]
naive = v2.roi_confidence_interval(paired, None, n_boot=800, seed=3)
clus = v2.roi_confidence_interval(paired, ids, n_boot=800, seed=3)
wn, wc = naive["ci_high"] - naive["ci_low"], clus["ci_high"] - clus["ci_low"]
print(f"c) 300 bets on 150 matches: naive width {wn:.3f}, clustered width {wc:.3f}  (x{wc/wn:.2f}; theory ~1.41)")
assert 1.2 < wc / wn < 1.7 and clus["n_clusters"] == 150 and naive["n_clusters"] == 300
# d) how many bets does it take to see a small edge? (odds 3.0, p=0.34 -> true ROI +2%)
print("d) true ROI +2% at odds 3.0 - interval half-width by number of bets:")
for n in (1000, 3000, 10000):
    ci = v2.roi_confidence_interval(simulate(rng, n, 0.34, 3.0), n_boot=300, seed=7)
    hw = (ci["ci_high"] - ci["ci_low"]) / 2
    print(f"   {n:6d} bets: ROI {ci['roi']:+.1%}, 95% interval [{ci['ci_low']:+.1%}, {ci['ci_high']:+.1%}] half-width {hw:.1%}, includes zero: {ci['includes_zero']}")
    if n == 1000: assert 0.05 < hw < 0.13
# the backtest wires the interval, uses match_id clustering, sorts by kickoff, and says so
recs = []
for i in range(60):
    for k in range(2):
        recs.append({"model_probability": .6, "decimal_odds": 2.0, "market_probability": .5, "won": i % 2 == 0,
                     "match_id": i, "kickoff": f"2026-0{1 + i % 9}-{10 + i % 15:02d}T15:00"})
rng2 = random.Random(5); rng2.shuffle(recs)
out = v2.backtest_flat_bets(recs, n_boot=300)
assert out["processed_chronologically"] and out["roi_confidence_interval"]["n_clusters"] == 60
assert any("includes zero" in w for w in out["warnings"]) == out["roi_confidence_interval"]["includes_zero"]
nok = v2.backtest_flat_bets([dict(r, kickoff=None) for r in recs], n_boot=100)
assert not nok["processed_chronologically"] and any("supplied order" in w for w in nok["warnings"])
assert v2.roi_confidence_interval([1.0])["ci_low"] is None            # one bet: no interval, said plainly
print("PASS")
