"""TEST 05 - backtests and tuning split by CALENDAR DATE.
BEFORE (v2.3.1): folds were cut by row count, so a matchday's matches could sit in both training and test.
AFTER (v2.4): no date is ever in both. Evidence is read from what the functions actually did."""
import _paths
import numpy as np, pandas as pd
import alea_predictor_v2_4_1 as a
from _common import make_matchday_league
old = _paths.optional_import("alea_predictor_v2_3_1")

# Real schedules are irregular (postponements, midweek replays), so row counts do not line up with dates.
# (On a PERFECTLY regular 10-matches-per-week schedule with step=40 the old row-count folds happen to land on
#  week boundaries and show no overlap - the problem only appears once the schedule is irregular.)
df, *_ = make_matchday_league(7, reschedule_prob=0.10)
day = df.Date.dt.normalize()

def capture_fits(mod):
    calls = []; real = mod.fit_model
    def spy(train, *args, **kw):
        calls.append(train.copy()); return real(train, *args, **kw)
    mod.fit_model = spy
    return calls, lambda: setattr(mod, "fit_model", real)

# ---------- walk-forward folds
if old is not None:
    calls, restore = capture_fits(old)
    old.walk_forward_backtest(df, min_train_matches=300, step=40, verbose=False, tune_each_fold=False)
    restore()
    overlap = 0
    for tr in calls:
        test = df.iloc[len(tr): len(tr) + 40]
        if set(tr.Date.dt.normalize()) & set(test.Date.dt.normalize()): overlap += 1
    print(f"BEFORE v2.3.1: {overlap}/{len(calls)} folds had a calendar date in BOTH training and test")
    assert overlap > 0, "expected the old row-count split to straddle at least one matchday on an irregular schedule"
rep, *_ = a.walk_forward_backtest(df, min_train_matches=300, step_days=14, verbose=False, tune_each_fold=False)
bad = [f for f in rep["fold_log"] if not (pd.Timestamp(f["train_max_date"]) < pd.Timestamp(f["test_min_date"]))]
print(f"AFTER  v2.4:   {len(bad)}/{rep['n_folds']} folds share a date (train_max < test_min checked on every fold); {rep['split_rule']}")
assert not bad and rep["n_folds"] > 5
# every training window used is exactly 'all matches dated before the cutoff'
for f in rep["fold_log"]:
    assert f["n_train"] == int((day < pd.Timestamp(f["cutoff"])).sum())

# ---------- tuning split (checked over 40 different irregular schedules, because whether the old 80% row
# boundary lands inside a matchday depends on the schedule)
def tune_overlap(mod, frame):
    calls, restore = capture_fits(mod)
    kw = {} if mod.__name__ == "alea_predictor_v2_3_1" else {"live": True}     # v2.4.1 requires an explicit cutoff
    try: mod.tune_params(frame, xi_candidates=[0.001], reg_candidates=[1.0], verbose=False, **kw)
    finally: restore()
    tr = calls[0]; valid = frame.iloc[len(tr):]          # sorted data: everything after the training block
    return len(set(tr.Date.dt.normalize()) & set(valid.Date.dt.normalize()))
n_old = n_new = 0; N = 40
for s in range(N):
    fr, *_ = make_matchday_league(100 + s, n_weeks=30, reschedule_prob=0.10)
    if old is not None: n_old += tune_overlap(old, fr) > 0
    n_new += tune_overlap(a, fr) > 0
if old is not None: print(f"BEFORE v2.3.1: tune_params validation split shared a calendar date with training in {n_old}/{N} schedules")
print(f"AFTER  v2.4:   shared a calendar date in {n_new}/{N} schedules")
assert n_new == 0
if old is not None: assert n_old > 0
# invalid settings fail loudly
try: a.walk_forward_backtest(df, min_train_matches=10**6, step_days=14, verbose=False); raise SystemExit("FAIL")
except ValueError: pass
try: a.walk_forward_backtest(df, step_days=0, verbose=False); raise SystemExit("FAIL")
except ValueError: pass
print("PASS")
