"""TEST 03 - FIX D3: a one-outcome 'market' was accepted (overround -47%).
Spec (agreed): a market needs >= 2 outcomes. A NEGATIVE overround is NOT rejected - best prices combined
from several bookmakers can legitimately sum below 100% - but it must produce a visible warning."""
import _paths
import alea_value_engine_v0_2_1 as v2
v1 = _paths.optional_import("alea_value_engine_v0_1")

if v1:
    m = v1.analyse_market({"a": 1.0}, {"a": 1.9})
    print(f"BEFORE v0.1: one-outcome market accepted, overround {m['market_overround_percent']:+.1f}%")
try:
    v2.analyse_market({"a": 1.0}, {"a": 1.9}); raise SystemExit("FAIL: one-outcome market accepted")
except ValueError as e:
    print("AFTER  v0.2: one-outcome market rejected ->", str(e)[:70])
# normal market: no warning
ok = v2.analyse_market({"home": .5, "draw": .27, "away": .23}, {"home": 2.05, "draw": 3.4, "away": 4.1})
assert ok["market_warnings"] == [] and ok["market_overround"] > 0
# best prices from different bookmakers can sum below 100%: accepted but warned
best = {"home": 2.30, "draw": 3.60, "away": 4.40}          # 1/2.3 + 1/3.6 + 1/4.4 = 0.9395
neg = v2.analyse_market({"home": .5, "draw": .27, "away": .23}, best)
assert neg["market_overround"] < 0
assert len(neg["market_warnings"]) == 1 and "Negative overround" in neg["market_warnings"][0]
assert neg["outcomes"]["home"]["expected_net_return_per_unit"] == .5 * 2.30 - 1     # EV maths unaffected
print(f"AFTER  v0.2: negative overround {neg['market_overround_percent']:+.2f}% accepted WITH warning:")
print("   ", neg["market_warnings"][0][:110], "...")
# still rejected: mismatched keys, empty, odds <= 1, NaN
for mp, od in (({}, {}), ({"a": .5, "b": .5}, {"a": 2, "c": 2}), ({"a": .5, "b": .5}, {"a": 1.0, "b": 2}),
               ({"a": float("nan"), "b": .5}, {"a": 2, "b": 2})):
    try: v2.analyse_market(mp, od); raise SystemExit("FAIL: accepted invalid market")
    except ValueError: pass
print("PASS")
