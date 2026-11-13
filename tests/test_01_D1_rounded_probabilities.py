"""TEST 01 - FIX D1: the value engine rejected ALEA's own predict() output.
predict() rounds probabilities to 4 decimals, so 1X2 can sum to 0.9999 or 1.0001; v0.1 demanded 1e-6.
BEFORE (v0.1): 19 of 56 pairings were rejected.   AFTER (v0.2): none, and bad input is still rejected."""
import _paths
import alea_predictor_v2_4_1 as a
import alea_value_engine_v0_2_1 as v2
from _common import make
v1 = _paths.optional_import("alea_value_engine_v0_1")

df, *_ = make(5, n_matches=500)
p = a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True); T = p["teams"]
fail1 = fail2 = N = 0; worst_sum_err = 0.0; max_ev_gap = 0.0
for h in T[:8]:
    for w in T[:8]:
        if h == w: continue
        q = a.predict(p, h, w); N += 1
        probs = {"home": q["p_home_win"], "draw": q["p_draw"], "away": q["p_away_win"]}
        odds = {"home": 2.0, "draw": 3.5, "away": 4.0}
        if v1:
            try: v1.analyse_market(probs, odds)
            except ValueError: fail1 += 1
        try:
            r = v2.analyse_market(probs, odds)
        except ValueError:
            fail2 += 1; continue
        worst_sum_err = max(worst_sum_err, r["probability_sum_error"])
        exact = v2.probabilities_from_prediction(q)          # full-precision, full-distribution reference
        for k in probs:
            ev_exact = exact[k] * odds[k] - 1
            max_ev_gap = max(max_ev_gap, abs(r["outcomes"][k]["expected_net_return_per_unit"] - ev_exact))
print(f"BEFORE v0.1: rejected {fail1}/{N} of ALEA's own predictions" if v1 else "v0.1 file not present - 'before' skipped")
print(f"AFTER  v0.2: rejected {fail2}/{N};  largest rounding error absorbed {worst_sum_err:.1e};  "
      f"largest EV difference vs full-precision matrix {max_ev_gap:.1e}")
assert fail2 == 0
assert max_ev_gap < 5e-4          # renormalised rounded probabilities give essentially the same EV
# bad input must STILL be rejected (the fix is a rounding allowance, not a removal of the check)
for bad in ({"home": .50, "draw": .27, "away": .22},      # sums to 0.99
            {"home": .50, "draw": .30, "away": .25}):     # sums to 1.05
    try: v2.analyse_market(bad, {"home": 2, "draw": 3.5, "away": 4}); raise SystemExit("FAIL: accepted a bad sum")
    except ValueError: pass
r = v2.analyse_market({"home": .5001, "draw": .2700, "away": .2300}, {"home": 2, "draw": 3.5, "away": 4})
assert abs(sum(o["model_probability"] for o in r["outcomes"].values()) - 1) < 1e-12   # renormalised exactly
# the engine consumes the exact grid too: matrix + tail must sum to 1, nothing is renormalised
q = a.predict(p, T[0], T[1]); g = v2.probabilities_from_score_matrix(q["matrix"].tolist(), q["tail_probability"])
assert abs(g["over_2_5"] - q["markets"]["over_2_5"]) < 1e-12            # totals are exact from the grid
assert 0 <= q["markets"]["home"] - g["home"] <= q["tail_probability"] + 1e-15  # 1X2 from the grid is a lower bound within the tail
print("PASS")
