"""TEST 02 - FIX D2: bool("False") is True in Python, so a lost bet read from a CSV was booked as a win.
BEFORE (v0.1): won='False' -> +1.0 units.   AFTER (v0.2): -1.0, and ambiguous values are rejected, not guessed."""
import _paths
import alea_value_engine_v0_2_1 as v2
v1 = _paths.optional_import("alea_value_engine_v0_1")

def rec(won): return {"model_probability": .6, "decimal_odds": 2.0, "market_probability": .5, "won": won}
def profit(mod, won): return mod.backtest_flat_bets([rec(won)])["net_profit_units"]

if v1: print(f"BEFORE v0.1: won='False' booked as {profit(v1, 'False'):+.1f} units (a loss counted as a win)")
for w in ("False", "false", "FALSE", " no ", "0", 0, False, "lost"):
    assert profit(v2, w) == -1.0, w
for w in ("True", "true", "TRUE", "yes", "1", 1, True, "won"):
    assert profit(v2, w) == 1.0, w
print("AFTER  v0.2: all false-like values -> -1.0, all true-like values -> +1.0")
for ambiguous in ("maybe", "", None, 2, -1, 0.5, "nan", [1]):
    out = v2.backtest_flat_bets([rec(ambiguous)])
    assert out["qualifying_bets"] == 0 and out["n_skipped_invalid_records"] == 1, ambiguous
print("AFTER  v0.2: ambiguous values are skipped AND counted, never guessed")
out = v2.backtest_flat_bets([rec("False"), rec("True"), rec("maybe")])
assert out["qualifying_bets"] == 2 and out["net_profit_units"] == 0.0 and out["n_skipped_invalid_records"] == 1
assert any("skipped" in w for w in out["warnings"])
print("PASS")
