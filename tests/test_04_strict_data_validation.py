"""TEST 04 - strict, fail-closed data validation.
BEFORE (v2.3.1): fit_model accepted duplicates, a team playing itself, a 60-goal score, a trailing-space
team name (creating a phantom extra team) and a match dated in 2031.
AFTER (v2.4): fit_model REFUSES such data (DataQualityError); clean_matches() drops/normalises each case
and lists the reason; too many rejected rows refuses the whole load."""
import _paths
import numpy as np, pandas as pd
import alea_predictor_v2_4_1 as a
from _common import make
old = _paths.optional_import("alea_predictor_v2_3_1")

base, teams, *_ = make(3, n_matches=500)
def mod(fn):
    d = base.copy(); fn(d); return d
cases = {   # name -> (dataframe, expected clean_matches reason or None if it is normalised not dropped)
 "duplicate fixture (identical)": (pd.concat([base, base.iloc[[5]]], ignore_index=True), "duplicate fixture (identical copy)"),
 "conflicting duplicate": (pd.concat([base, base.iloc[[5]].assign(FTHG=base.FTHG.iloc[5] + 3)], ignore_index=True),
                           "conflicting duplicate (same fixture, different scores)"),
 "team plays itself": (mod(lambda d: d.__setitem__("AwayTeam", d.AwayTeam.where(d.index != 3, d.HomeTeam))), "team plays itself"),
 "non-integer goals": (mod(lambda d: (d.__setitem__("FTHG", d.FTHG.astype(float)), d.__setitem__("FTHG", d.FTHG.where(d.index != 2, 2.5)))), "non-integer goals"),
 "negative goals": (mod(lambda d: d.__setitem__("FTHG", d.FTHG.where(d.index != 6, -1))), "negative goals"),
 "60-goal score": (mod(lambda d: d.__setitem__("FTHG", d.FTHG.where(d.index != 4, 60))), "implausible goals (> 15)"),
 "match dated 2031": (mod(lambda d: d.__setitem__("Date", d.Date.where(d.index != 9, pd.Timestamp("2031-01-01")))), "played match dated in the future"),
 "missing goals": (mod(lambda d: (d.__setitem__("FTAG", d.FTAG.astype(float)), d.__setitem__("FTAG", d.FTAG.where(d.index != 8, np.nan)))), "missing/non-numeric goals"),
 "unreadable date": (mod(lambda d: (d.__setitem__("Date", d.Date.astype(object)), d.__setitem__("Date", d.Date.where(d.index != 11, "not a date")))), "invalid date"),
}
print(f"{'case':32s} {'v2.3.1 fit':14s} {'v2.4 fit':10s} v2.4 clean_matches")
for name, (df, reason) in cases.items():
    before = "n/a"
    if old is not None:
        try: old.fit_model(df.assign(Date=pd.to_datetime(df.Date, errors="coerce")).dropna(subset=["Date"]), xi=0.0018, reg=1.0, verbose=False); before = "ACCEPTED"
        except Exception: before = "rejected"
    try: a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True); raise SystemExit(f"FAIL: v2.4 fit_model accepted {name}")
    except a.DataQualityError: after = "REFUSED"
    clean, rep = a.clean_matches(df, verbose=False, max_reject_fraction=0.05)
    assert reason in rep["reason_counts"], (name, rep["reason_counts"])
    p = a.fit_model(clean, xi=0.0018, reg=1.0, verbose=False, live=True)         # cleaned data is accepted
    assert len(p["teams"]) == len(teams)
    print(f"{name:32s} {before:14s} {after:10s} dropped: {reason}")
# conflicting duplicates must drop BOTH copies (we cannot know which score is right)
_, rep = a.clean_matches(cases["conflicting duplicate"][0], verbose=False, max_reject_fraction=0.05)
assert sum("conflicting" in r for rr in rep["rejected"] for r in rr["reasons"]) == 2
# identical duplicate keeps exactly one copy
clean, _ = a.clean_matches(cases["duplicate fixture (identical)"][0], verbose=False, max_reject_fraction=0.05)
assert len(clean) == len(base)

# names: whitespace / FC suffix are NORMALISED (no phantom team), not dropped
d = base.copy(); d.loc[7, "HomeTeam"] = d.loc[7, "HomeTeam"] + "  "; d.loc[9, "AwayTeam"] = d.loc[9, "AwayTeam"] + " FC"
if old is not None:
    po = old.fit_model(d, xi=0.0018, reg=1.0, verbose=False)
    print(f"{'trailing space / FC suffix':32s} v2.3.1 built {len(po['teams'])} teams (true {len(teams)}) -> phantom teams")
    assert len(po["teams"]) > len(teams)
try: a.fit_model(d, xi=0.0018, reg=1.0, verbose=False, live=True); raise SystemExit("FAIL: non-canonical names accepted by fit_model")
except a.DataQualityError: pass
clean, rep = a.clean_matches(d, verbose=False)
assert rep["rejected"] == [] and set(clean.HomeTeam) | set(clean.AwayTeam) == set(teams)
print(f"{'trailing space / FC suffix':32s} v2.4 normalised, {len(set(clean.HomeTeam)|set(clean.AwayTeam))} teams (true {len(teams)})")

# too much bad data refuses the whole load (the source format has probably changed)
bad = base.copy(); bad.loc[:60, "FTHG"] = -1
try: a.clean_matches(bad, verbose=False); raise SystemExit("FAIL: heavy corruption accepted")
except a.DataQualityError as e: print("12% corrupted rows -> load refused:", str(e)[:70])
# ALEA(data=...) runs the same gate and keeps a record
one_bad = base.copy(); one_bad.loc[3, "FTHG"] = 60
m = a.ALEA(data=one_bad, xi=0.0018, reg=1.0)
assert len(m.cleaning_report["rejected"]) == 1 and m.cleaning_report["rejected"][0]["reasons"] == ["implausible goals (> 15)"]
print("PASS")
