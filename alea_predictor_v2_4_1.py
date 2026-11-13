"""
ALEA - Dixon-Coles Poisson Match Predictor
-------------------------------------------
Time-weighted attack/defence model + tau (rho) low-score correction.

v2.0 changes from the original draft:
  - API key no longer hardcoded - read from an environment variable
  - Real backtesting: walk-forward (chronological, never random), with
    Brier score, log loss and Ranked Probability Score (RPS), plus a
    calibration table and baseline comparisons. This was missing
    entirely before - without it you can't know if any prediction out
    of this file means anything.
  - xi (time-decay) is now tuned against a validation split instead of
    being a guessed constant.
  - The made-up "expected_corners_proxy" formula is gone. Corners are
    now estimated from real HC/AC data (football-data.co.uk) with a
    simple time-weighted average model - deliberately simpler than the
    goals model, clearly labelled as such.
  - Shin's method added to de-vig bookmaker odds, so backtest results
    can be compared against the market, not just against each other.
  - Every fitted model now carries a version tag, fit timestamp, and
    the date range / row count of the data it was trained on, so a
    saved prediction is traceable later.
  - save_model() / load_model() so you don't need to refit from
    scratch every run.
  - Basic data validation (negative goals, duplicate fixtures, etc.)
    runs automatically when data loads.

v2.4.1 (two corrections; v2.3.1 still frozen, nothing else changed):
  1. HISTORICAL CUTOFF ENFORCED INSIDE fit_model (and tune_params / fit_corner_rates).
     Every fit needs an explicit cutoff: either as_of_date=<date or datetime> (historical
     prediction) or live=True (training the current model today). Passing neither, or both,
     is an error. A training match dated on/after the cutoff is rejected (FutureDataError).
     Same-day policy (documented): default "exclude" = only matches dated strictly BEFORE the
     cutoff date are allowed. same_day="timestamp" allows a match on the cutoff date only if its
     kickoff time is known and kickoff + MATCH_COMPLETION_MINUTES <= the as_of timestamp.
     There is no parameter that disables the check. All backtest folds, aligned-odds folds and
     tuning splits pass their own cutoff. Each fitted model records its cutoff.
  2. SCORE PROBABILITIES ARE EXACT. score_matrix() no longer clips or renormalises: its cells
     are the true Dixon-Coles probabilities and sum to 1 - tail, where the tail (probability of
     more than MAX_GOALS goals by either side) is reported, never redistributed. 1X2,
     over/under and BTTS are computed over the FULL distribution in closed form (Skellam
     distribution + Poisson total-goals distribution + the exact Dixon-Coles corrections), not
     from the grid, so a bigger grid is not needed for correctness and the numbers are
     identical for any grid size.

v2.4 adds (each fix has its own test in tests/; v2.3.1 is frozen and untouched):
  - Strict, fail-closed data validation (clean_matches / assert_training_data_valid):
    duplicates, a team playing itself, non-integer/negative/implausible scores,
    played matches dated in the future and unreadable names are rejected and
    listed with reasons. fit_model refuses data that has not passed this gate.
  - Backtests split by CALENDAR DATE (no matchday is ever in both train and
    test), and the tuning split does the same.
  - Score grid 0..15 instead of 0..8; predict() reports the probability mass
    left outside the grid.
  - Model files are versioned (alea_model_<version>.json); load_model refuses a
    file written by a different version unless you explicitly allow it.
  - Odds-timing-aware market comparison (aligned_market_backtest): the model
    only sees results that were available when the odds were collected, model
    and market are scored on the SAME matches, with paired bootstrap intervals.
    The old market numbers inside walk_forward_backtest are gone because they
    compared a model trained on all results with early odds (and scored the
    model on all matches but the market only on those with odds).
  - Teams with no training data get a league-average prior (attack 0, defence =
    league mean) and are clearly flagged, instead of crashing. A name that is
    unknown AND not in the data source's team list (a typo) is still an error,
    with suggestions, never silently treated as a new team.

v2.3 adds (found by actually investigating the first real backtest):
  - ROOT CAUSE of "Invalid Dixon-Coles score matrix" in backtest folds:
    the correction factors (1 - lam*mu*rho, 1 + lam*rho, 1 + mu*rho,
    1 - rho) can go <= 0 for a team PAIRING that never happened, and
    the old fit only checked pairings that did. v2.1 hid this by
    clipping negatives to 0; v2.2 exposed it. Now rho is constrained
    during the fit to the range that keeps those factors positive for
    EVERY possible home/away pairing, so a fitted model is valid for
    every fixture by construction (rho_valid_interval()).
  - Shrinkage (ridge penalty, strength `reg`): teams with few matches
    (e.g. newly promoted) are pulled toward league average instead of
    getting extreme attack/defence values from a handful of games.
    `reg` is tuned on a validation split together with xi
    (tune_params), never on the data being predicted.
  - tune_params(): one failed candidate no longer aborts the whole
    tuning - it is skipped and counted.
  - Data freshness: the loader warns when the newest result is much
    older than today, and when the source lists past-dated matches
    with no score (i.e. the upstream file is behind real life).
    predict() reports the data age; explain() flags it.
  - explain() flags a team with very little training data.

v2.1 adds:
  - load_from_openfootball(): pulls from github.com/openfootball/
    football.json - free, public domain, no API key, auto-updated
    daily. This is now the DEFAULT source because it's the only one
    of the two that also carries each season's still-unplayed
    fixtures (the CSV source is a pure historical-results archive -
    it has no future matches in it at all).
  - Any still-unplayed fixture found in that data is kept separately
    (self.fixtures) instead of being dropped, so upcoming real
    fixtures - with real dates - can be predicted automatically
    instead of you hand-typing a guessed list of team names.
  - explain(): a one-paragraph, plain-language answer to "what's the
    probability A beats B" - states the data cutoff, names the method
    (time-weighted Poisson + Dixon-Coles low-score correction) and
    rho, then gives the number. ALEA.explain(home, away) and
    ALEA.upcoming(n) both use it.
  - Trade-off to know about: openfootball has no corners or odds
    columns, so when you use it (the default now) the corners model
    and the market-comparison part of the backtest are both silently
    skipped - the code already degraded gracefully for missing
    columns, this just means that path gets used now. Pass
    source="footballdata" to ALEA() if you want corners/odds back and
    don't need upcoming fixtures.
"""

import os
import json
import hashlib
import difflib
import requests
import numpy as np
import pandas as pd
from scipy.optimize import minimize, brentq
from scipy.stats import poisson, skellam
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")


# ============================================================
# CONFIG
# ============================================================

API_KEY  = os.environ.get("FOOTBALL_API_KEY")   # set this in your shell - never hardcode a real key here
API_BASE = "https://footballapi.org"             # change when you have working docs

MAX_GOALS     = 15       # scoreline grid 0..15 (v2.3.1: 0..8). Omitted mass is reported by predict().
MATCH_COMPLETION_MINUTES = 150  # same-day "timestamp" policy: a match counts as finished this long after kickoff
MAX_PLAUSIBLE_GOALS = 15  # a played match with more goals than this on one side is treated as a data error
TRUNC_WARN    = 1e-4     # warn if more than this probability mass falls outside the score grid
XI            = 0.0018   # fallback time-decay if you don't run tune_params()
REG           = 1.0      # fallback shrinkage strength (0 = none) if you don't run tune_params()
RHO_CAP       = 0.3      # |rho| never above this (typical fitted values are around -0.1)
SAFETY        = 0.98     # every Dixon-Coles correction factor stays >= 1-SAFETY (= 0.02) > 0
LOW_DATA_N    = 10       # fewer than this many training matches for a team = flagged in explain()
STALE_DAYS    = 14       # newest result older than this = data-freshness warning
MODEL_VERSION = "alea-dc-v2.4.1"
DISCLAIMER    = "Model output only - probabilities, not certainties. No betting advice, no guaranteed edge."


# ============================================================
# 1. DATA
# ============================================================

CORE_COLS  = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
EXTRA_COLS = ["HC", "AC", "B365H", "B365D", "B365A",    # early (pre-match) 1X2 odds
              "B365CH", "B365CD", "B365CA",              # closing 1X2 odds (Football-Data: "C" prefix, from 2019/20)
              "Time"]                                    # optional - kept when present, skipped when not


def validate_data(data):
    """
    Basic sanity checks before trusting this data for fitting.
    Bad rows (negative goals, duplicate fixtures, a team playing
    itself) silently corrupt a fit with no error message otherwise -
    this catches the obvious cases.
    """
    issues = []
    if (data.FTHG < 0).any() or (data.FTAG < 0).any():
        issues.append("negative goal values found")
    if (data.FTHG > 15).any() or (data.FTAG > 15).any():
        issues.append("goal values above 15 found - check for data errors")
    dup = data.duplicated(subset=["Date", "HomeTeam", "AwayTeam"]).sum()
    if dup:
        issues.append(f"{dup} duplicate fixture rows")
    same_team = (data.HomeTeam == data.AwayTeam).sum()
    if same_team:
        issues.append(f"{same_team} rows where HomeTeam == AwayTeam")

    if issues:
        print("  Data validation warnings:")
        for i in issues:
            print(f"    - {i}")
    else:
        print("  Data validation: no issues found.")
    return issues


class DataQualityError(ValueError):
    """Raised when match data fails strict validation (fail-closed)."""


def _goal_problems(df):
    """Per-row list of goal-related problems for FTHG/FTAG."""
    probs = [[] for _ in range(len(df))]
    for col in ("FTHG", "FTAG"):
        num = pd.to_numeric(df[col], errors="coerce")
        for k, v in enumerate(num.values):
            if not np.isfinite(v):
                probs[k].append("missing/non-numeric goals")
            elif v != np.floor(v):
                probs[k].append("non-integer goals")
            elif v < 0:
                probs[k].append("negative goals")
            elif v > MAX_PLAUSIBLE_GOALS:
                probs[k].append(f"implausible goals (> {MAX_PLAUSIBLE_GOALS})")
    return probs


def clean_matches(data, today=None, max_reject_fraction=0.02, verbose=True):
    """
    Strict gate for PLAYED matches. Returns (clean_dataframe, report).
    Rows are dropped - never silently repaired - and every drop is listed with
    its reason. Checks:
      - required columns present
      - team names readable; normalised with the same canonical rules used
        everywhere else (whitespace, FC/AFC suffix, alias table)
      - date readable and not in the future (a PLAYED match cannot be tomorrow)
      - goals present, integer, >= 0, <= MAX_PLAUSIBLE_GOALS
      - a team never plays itself
      - duplicates: identical copies keep the first; the same fixture with
        DIFFERENT scores is dropped entirely (we cannot know which is right)
    Fail-closed: if more than `max_reject_fraction` of rows are rejected the
    whole load is refused, because that usually means the source changed format.
    """
    required = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise DataQualityError(f"match data is missing required columns: {missing}")
    df = data.copy().reset_index(drop=True)
    n_in = len(df)
    reasons = [[] for _ in range(n_in)]

    df["HomeTeam"] = df["HomeTeam"].map(_team_name)
    df["AwayTeam"] = df["AwayTeam"].map(_team_name)
    for k in range(n_in):
        if df.at[k, "HomeTeam"] is None or df.at[k, "AwayTeam"] is None:
            reasons[k].append("missing/unreadable team name")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    limit = pd.Timestamp(today if today is not None else datetime.now().date()).normalize() + pd.Timedelta(days=1)
    for k, d in enumerate(df["Date"].values):
        if pd.isna(d):
            reasons[k].append("invalid date")
        elif pd.Timestamp(d) >= limit:
            reasons[k].append("played match dated in the future")
    for k, pr in enumerate(_goal_problems(df)):
        reasons[k].extend(pr)
    same = (df["HomeTeam"] == df["AwayTeam"]) & df["HomeTeam"].notna()
    for k in np.flatnonzero(same.values):
        reasons[k].append("team plays itself")

    ok = [k for k in range(n_in) if not reasons[k]]
    groups = {}
    for k in ok:
        key = (pd.Timestamp(df.at[k, "Date"]).normalize(), df.at[k, "HomeTeam"], df.at[k, "AwayTeam"])
        groups.setdefault(key, []).append(k)
    for key, rows in groups.items():
        if len(rows) > 1:
            scores = {(int(float(df.at[r, "FTHG"])), int(float(df.at[r, "FTAG"]))) for r in rows}
            if len(scores) == 1:
                for r in rows[1:]:
                    reasons[r].append("duplicate fixture (identical copy)")
            else:
                for r in rows:
                    reasons[r].append("conflicting duplicate (same fixture, different scores)")

    keep = [k for k in range(n_in) if not reasons[k]]
    clean = df.iloc[keep].copy()
    clean["FTHG"] = clean["FTHG"].astype(float).astype(int)
    clean["FTAG"] = clean["FTAG"].astype(float).astype(int)
    clean = clean.sort_values("Date").reset_index(drop=True)

    counts = {}
    for rs in reasons:
        for r in rs:
            counts[r] = counts.get(r, 0) + 1
    rejected = [{"row": k, "date": str(df.at[k, "Date"])[:10], "home": df.at[k, "HomeTeam"],
                 "away": df.at[k, "AwayTeam"], "reasons": reasons[k]}
                for k in range(n_in) if reasons[k]]
    report = {"input_rows": n_in, "kept": len(clean), "rejected": rejected, "reason_counts": counts}
    if verbose:
        if rejected:
            print(f"  Data cleaning: kept {len(clean)} of {n_in} rows; rejected {len(rejected)}:")
            for r, c in sorted(counts.items(), key=lambda x: -x[1]):
                print(f"    - {c} x {r}")
        else:
            print(f"  Data cleaning: all {n_in} rows passed strict validation.")
    if n_in and len(rejected) / n_in > max_reject_fraction:
        raise DataQualityError(
            f"{len(rejected)} of {n_in} rows ({len(rejected)/n_in:.1%}) were rejected, more than the "
            f"{max_reject_fraction:.0%} limit - the source format has probably changed. Reasons: {counts}")
    if clean.empty:
        raise DataQualityError("no valid matches remain after cleaning")
    return clean, report


def assert_training_data_valid(data, today=None):
    """Strict check used by fit_model: it does not repair anything, it refuses.
    Data should come from clean_matches() (the loaders and ALEA() already do that)."""
    required = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise DataQualityError(f"Training data missing columns: {sorted(missing)}")
    problems = {}
    def add(msg, n):
        if n:
            problems[msg] = int(n)
    add("missing values in required columns", data[required].isna().any(axis=1).sum())
    if not pd.api.types.is_datetime64_any_dtype(data["Date"]):
        problems["Date column is not datetime"] = len(data)
    else:
        limit = pd.Timestamp(today if today is not None else datetime.now().date()).normalize() + pd.Timedelta(days=1)
        add("played match dated in the future", (data["Date"] >= limit).sum())
    gp = _goal_problems(data.reset_index(drop=True))
    for msg in sorted({m for pr in gp for m in pr}):
        add(msg, sum(msg in pr for pr in gp))
    add("team plays itself", (data["HomeTeam"] == data["AwayTeam"]).sum())
    add("duplicate fixture rows", data.duplicated(subset=["Date", "HomeTeam", "AwayTeam"]).sum())
    for col in ("HomeTeam", "AwayTeam"):
        canon = data[col].map(lambda x: _team_name(x) if isinstance(x, str) else None)
        add(f"{col} not in canonical form (spaces/aliases) - run clean_matches()", (canon != data[col]).sum())
    if problems:
        raise DataQualityError("Training data failed strict validation: " +
                               "; ".join(f"{k}: {v} row(s)" for k, v in problems.items()))


def load_from_csv(seasons=("2425", "2526", "2627")):
    """Reliable free source - works right now."""
    frames = []
    for s in seasons:
        url = f"https://www.football-data.co.uk/mmz4281/{s}/E0.csv"
        try:
            df = pd.read_csv(url)
            df["Season"] = s
            frames.append(df)
            print(f"  {s}: {len(df)} matches")
        except Exception as e:
            print(f"  {s} failed: {e}")
    if not frames:
        raise RuntimeError("No data loaded")
    data = pd.concat(frames, ignore_index=True)

    keep = [c for c in CORE_COLS + EXTRA_COLS if c in data.columns]
    missing_extra = [c for c in EXTRA_COLS if c not in data.columns]
    data = data[keep].dropna(subset=CORE_COLS).copy()
    data["Date"] = pd.to_datetime(data["Date"], dayfirst=True, errors="coerce")
    data, report = clean_matches(data)

    if missing_extra:
        print(f"  Note: columns not in this data, related features will be skipped: {missing_extra}")
    print(f"Total: {len(data)} matches  ({data.Date.min().date()} -> {data.Date.max().date()})")
    data.attrs["cleaning_report"] = report
    return data


def load_from_api(date_from=None, date_to=None):
    """
    Placeholder for your footballapi.org key. Largely superseded by
    load_from_openfootball() below, which needs no key at all - keep
    this around only if you later want a paid/richer source.
    Fill in the exact endpoint + response shape when the key works.
    Must return a DataFrame with columns: Date, HomeTeam, AwayTeam, FTHG, FTAG
    (and ideally HC, AC, B365H, B365D, B365A too, if the API has them).
    """
    if not API_KEY:
        raise RuntimeError(
            "FOOTBALL_API_KEY environment variable is not set. "
            "Set it before calling this function - see the setup guide. "
            "load_from_csv() works without it in the meantime."
        )
    headers = {"X-Auth-Token": API_KEY}   # or X-Api-Key / Authorization - adjust to the real API
    # Example (change to the real endpoint once you have working docs):
    # url = f"{API_BASE}/matches?competition=PL&status=FINISHED"
    # r = requests.get(url, headers=headers, timeout=30)
    # r.raise_for_status()
    # ... parse JSON into the columns above ...
    raise NotImplementedError("Endpoint/response shape not filled in yet. Using CSV fallback for now.")


# FIX 2: Canonicalise names so source suffixes do not create duplicate teams.
TEAM_ALIASES = {
    "man utd": "Manchester United",
    "manchester utd": "Manchester United",
    "man city": "Manchester City",
    "spurs": "Tottenham Hotspur",
    "wolves": "Wolverhampton Wanderers",
}

def _team_name(x):
    """Accept plain names or older {name/key: ...} team objects."""
    if isinstance(x, dict):
        x = x.get("name") or x.get("key")
    if not isinstance(x, str):
        return None
    name = " ".join(x.strip().split())
    if not name:
        return None
    if name.upper().endswith(" FC"):
        name = name[:-3].strip()
    elif name.upper().endswith(" AFC"):
        name = name[:-4].strip()
    return TEAM_ALIASES.get(name.casefold(), name)


def check_freshness(data, unresolved_rows, today, stale_days=STALE_DAYS):
    """
    Is the data keeping up with real life? A model can run perfectly and
    still predict badly from stale data, so this is checked and printed
    every load instead of being left for you to notice.

    Two separate signals:
      1. newest played result is more than `stale_days` days old. This
         is NOT automatically a problem - international breaks create
         real gaps of about two weeks - so it is worded as 'check', not 'bug'.
      2. the source lists matches dated on/before today with no score
         (excluding postponed/cancelled ones). That one is strong
         evidence the upstream file is behind real results.
    Returns a dict (also stored on data.attrs["freshness"]).
    """
    newest = pd.Timestamp(data.Date.max()).normalize()
    age_days = int((today - newest).days)
    gone = ("postponed", "cancelled", "canceled", "abandoned")
    past_missing = [r for r in unresolved_rows
                    if r["Date"] < today and not any(g in str(r["Status"]) for g in gone)]
    info = {
        "newest_result": str(newest.date()),
        "age_days": age_days,
        "past_without_result": len(past_missing),
        "newest_past_without_result": (str(max(r["Date"] for r in past_missing).date())
                                       if past_missing else None),
        "warnings": [],
    }
    if past_missing:
        info["warnings"].append(
            f"{len(past_missing)} matches dated on/before {today.date()} have NO result in the source "
            f"(latest: {info['newest_past_without_result']}). The upstream file is probably behind "
            f"real results - predictions only use matches through {info['newest_result']}.")
    if age_days > stale_days:
        info["warnings"].append(
            f"Newest result in the data is {age_days} days old ({info['newest_result']}). "
            f"An international break can explain ~2 weeks; more than that means the source is lagging.")
    for w in info["warnings"]:
        print(f"  WARNING (data freshness): {w}")
    if not info["warnings"]:
        print(f"  Data freshness OK: newest result {info['newest_result']} ({age_days} day(s) ago).")
    data.attrs["freshness"] = info
    return info


def load_from_openfootball(seasons=("2024-25", "2025-26", "2026-27"),
                           league="en.1", as_of_date=None):
    """
    Load played matches and future fixtures separately.
    FIX 1: supports dict score objects safely; bare score arrays are ambiguous.
    FIX 6: past matches with missing results are unresolved, not upcoming.
    """
    played_rows, fixture_rows, unresolved_rows = [], [], []
    today = pd.Timestamp(as_of_date or datetime.now().date()).normalize()

    for season in seasons:
        url = f"https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{league}.json"
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
                raise ValueError("unexpected JSON structure: expected a matches list")
        except Exception as exc:
            print(f"  {season}: failed to load ({exc})")
            continue

        n_played = n_upcoming = n_unresolved = n_skipped = 0
        for match in payload["matches"]:
            if not isinstance(match, dict):
                n_skipped += 1
                continue
            date_value = match.get("date")
            home = _team_name(match.get("team1"))
            away = _team_name(match.get("team2"))
            if not date_value or not home or not away:
                n_skipped += 1
                continue
            match_date = pd.to_datetime(date_value, errors="coerce")
            if pd.isna(match_date):
                n_skipped += 1
                continue
            match_date = pd.Timestamp(match_date).normalize()

            score = match.get("score")
            ft = score.get("ft") if isinstance(score, dict) else None
            # Some data snapshots use a bare pair. Do not treat a future
            # [0, 0] placeholder as a played 0-0 result.
            if ft is None and isinstance(score, (list, tuple)) and match_date < today:
                ft = score
            valid_ft = (
                isinstance(ft, (list, tuple)) and len(ft) == 2
                and all(isinstance(v, (int, float, np.integer, np.floating))
                        and np.isfinite(v) and float(v).is_integer() and v >= 0
                        for v in ft)
            )
            status = str(match.get("status", "")).strip().casefold()
            cancelled = any(x in status for x in
                            ("postponed", "cancelled", "canceled", "abandoned"))

            if valid_ft:
                played_rows.append({
                    "Date": match_date, "HomeTeam": home, "AwayTeam": away,
                    "FTHG": int(ft[0]), "FTAG": int(ft[1]), "Season": season,
                })
                n_played += 1
            elif match_date >= today and not cancelled:
                fixture_rows.append({
                    "Date": match_date, "HomeTeam": home, "AwayTeam": away,
                    "Season": season, "Status": status or "unplayed",
                })
                n_upcoming += 1
            else:
                unresolved_rows.append({
                    "Date": match_date, "HomeTeam": home, "AwayTeam": away,
                    "Season": season, "Status": status or "missing result",
                })
                n_unresolved += 1

        print(f"  {season}: {n_played} played, {n_upcoming} upcoming, "
              f"{n_unresolved} past/unresolved, {n_skipped} malformed")

    if not played_rows:
        raise RuntimeError("No played matches loaded from openfootball - check season/league codes.")
    data = pd.DataFrame(played_rows)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data, report = clean_matches(data, today=today)
    print(f"Total: {len(data)} played matches ({data.Date.min().date()} -> {data.Date.max().date()})")
    data.attrs["cleaning_report"] = report

    fixtures = pd.DataFrame(fixture_rows)
    if not fixtures.empty:
        fixtures["Date"] = pd.to_datetime(fixtures["Date"], errors="coerce")
        fixtures = fixtures.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    print(f"Upcoming fixtures found: {len(fixtures)}")
    if unresolved_rows:
        print(f"Past/unresolved fixtures excluded from upcoming list: {len(unresolved_rows)}")
    check_freshness(data, unresolved_rows, today)
    return data, fixtures


def tau(h, a, lam, mu, rho):
    """Dixon-Coles low-score correction (scalar version, for reference)."""
    if h == 0 and a == 0:
        return 1 - lam * mu * rho
    if h == 0 and a == 1:
        return 1 + lam * rho
    if h == 1 and a == 0:
        return 1 + mu * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def tau_vec(hg, ag, lam, mu, rho):
    """Vectorised tau."""
    t = np.ones(len(hg), dtype=float)
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    t[m00] = 1 - lam[m00] * mu[m00] * rho
    t[m01] = 1 + lam[m01] * rho
    t[m10] = 1 + mu[m10] * rho
    t[m11] = 1 - rho
    return t  # FIX 4: preserve invalid values so fitting can reject them


def rho_valid_interval(att, deff, home_adv):
    """
    The range of rho for which every Dixon-Coles correction factor is
    positive for EVERY possible home/away pairing of the teams in the
    model (not just the pairings that happened to be played):

        1 - lam*mu*rho > 0     ->  rho < 1/(lam*mu)
        1 + lam*rho    > 0     ->  rho > -1/lam
        1 + mu*rho     > 0     ->  rho > -1/mu
        1 - rho        > 0     ->  rho < 1

    where, for home team i and away team j:
        lam = exp(att[i] + deff[j] + home_adv)     (home expected goals)
        mu  = exp(att[j] + deff[i])                (away expected goals)

    Each is tightened by SAFETY (factor stays >= 1 - SAFETY = 0.02) and
    rho is also capped at +/-RHO_CAP. This is the actual fix for the
    'Invalid Dixon-Coles score matrix' errors: before, only observed
    scorelines were checked, so a never-played pairing (strong attack at
    home vs weak defence) could still have a negative probability.
    Returns (lo, hi) with lo < 0 < hi. Returns None if the strengths are
    so extreme that exp() overflows.
    """
    n = len(att)
    lam = np.exp(att[:, None] + deff[None, :] + home_adv)   # [home i, away j]
    mu = np.exp(att[None, :] + deff[:, None])
    off = ~np.eye(n, dtype=bool)                              # a team never plays itself
    lam, mu = lam[off], mu[off]
    if not (np.all(np.isfinite(lam)) and np.all(np.isfinite(mu))):
        return None
    lo = max(-SAFETY / lam.max(), -SAFETY / mu.max(), -RHO_CAP)
    hi = min(SAFETY / (lam * mu).max(), SAFETY, RHO_CAP)
    return float(lo), float(hi)


def _rho_from_z(z, lo, hi):
    """Smoothly map an unconstrained number z into (lo, hi). The optimiser
    works on z, so rho can never leave the valid range."""
    return lo + (hi - lo) / (1.0 + np.exp(-z))


def check_all_pairings_valid(params):
    """Explicit proof, not an assumption: every home/away pairing of the
    fitted teams has all four correction factors > 0. Raises if not."""
    teams = params["teams"]
    att = np.array([params["attack"][t] for t in teams])
    deff = np.array([params["defence"][t] for t in teams])
    rho = params["rho"]
    lam = np.exp(att[:, None] + deff[None, :] + params["home_adv"])
    mu = np.exp(att[None, :] + deff[:, None])
    off = ~np.eye(len(teams), dtype=bool)
    lam, mu = lam[off], mu[off]
    worst = min((1 - lam * mu * rho).min(), (1 + lam * rho).min(),
                (1 + mu * rho).min(), 1 - rho)
    if not np.isfinite(worst) or worst <= 0:
        raise RuntimeError(f"Fitted model is invalid for some pairing (smallest factor {worst:.4f}).")
    return float(worst)


class FutureDataError(DataQualityError):
    """A training match is dated on/after the prediction cutoff (future information)."""


def _resolve_cutoff(as_of_date, live, same_day):
    """Validate the cutoff arguments of a fit. EXACTLY ONE of as_of_date / live=True is required:
    a historical prediction must name its cutoff, and training the current model must say so."""
    if same_day not in ("exclude", "timestamp"):
        raise ValueError("same_day must be 'exclude' or 'timestamp'.")
    if live and as_of_date is not None:
        raise ValueError("Give EITHER as_of_date (historical prediction) OR live=True (train the current "
                         "model today), not both.")
    if not live and as_of_date is None:
        raise ValueError(
            "A cutoff is mandatory. Pass as_of_date=<the prediction date> when training for a historical "
            "prediction/backtest, or live=True when training the current model today. Without it there is no "
            "guarantee that matches after the prediction date stay out of training.")
    if live:
        if same_day != "exclude":
            raise ValueError("same_day only applies to as_of_date; live training uses today's results by definition.")
        today = pd.Timestamp(datetime.now().date())
        return {"mode": "live", "as_of": today + pd.Timedelta(days=1), "same_day": "exclude", "label": str(today.date())}
    try:
        as_of = pd.Timestamp(as_of_date)
    except Exception as exc:
        raise ValueError(f"as_of_date could not be read as a date/time: {as_of_date!r}") from exc
    if pd.isna(as_of):
        raise ValueError("as_of_date is empty/NaT.")
    if as_of.tzinfo is not None:
        raise ValueError("as_of_date must be timezone-naive, in the same timezone as the match Date/Time columns.")
    if same_day == "timestamp" and as_of == as_of.normalize():
        raise ValueError("same_day='timestamp' needs an as_of_date that includes a time of day.")
    return {"mode": "historical", "as_of": as_of, "same_day": same_day, "label": str(as_of)}


def _kickoff_times(data):
    """Kickoff datetime per row from a 'Kickoff' column, else Date + 'Time' (HH:MM); NaT when unknown."""
    if "Kickoff" in data.columns:
        return pd.to_datetime(data["Kickoff"], errors="coerce")
    if "Time" in data.columns:
        t = data["Time"].astype(str).str.strip()
        t = t.where(t.str.count(":") != 1, t + ":00")
        return pd.to_datetime(data["Date"], errors="coerce").dt.normalize() + pd.to_timedelta(t, errors="coerce")
    return pd.Series(pd.NaT, index=data.index, dtype="datetime64[ns]")


def enforce_cutoff(data, cutoff):
    """
    Reject any training match that is not provably earlier than the cutoff. Called inside every fit,
    and there is no switch to turn it off.
      same_day='exclude'   : a match is allowed only if its DATE is strictly before the cutoff date.
      same_day='timestamp' : matches dated after the cutoff date are rejected; a match ON the cutoff
                             date is allowed only if kickoff + MATCH_COMPLETION_MINUTES <= as_of
                             (unknown kickoff time = rejected).
    """
    day = pd.to_datetime(data["Date"], errors="coerce").dt.normalize()
    if bool(day.isna().any()):
        # a match whose date cannot be read cannot be proven earlier than the cutoff: fail closed
        raise DataQualityError(f"{int(day.isna().sum())} training match(es) have a missing/unreadable Date, "
                               f"so they cannot be shown to precede the cutoff {cutoff['as_of']}.")
    as_of = cutoff["as_of"]
    cd = as_of.normalize()
    if cutoff["same_day"] == "exclude":
        bad = day >= cd
    else:
        bad = day > cd
        on_day = day == cd
        if on_day.any():
            finished = (_kickoff_times(data) + pd.Timedelta(minutes=MATCH_COMPLETION_MINUTES)) <= as_of
            bad = bad | (on_day & ~finished.fillna(False))
    if bool(bad.any()):
        ex = data.loc[bad].head(3)
        shown = "; ".join(f"{pd.Timestamp(r.Date).date()} {r.HomeTeam} v {r.AwayTeam}" for r in ex.itertuples())
        raise FutureDataError(
            f"{int(bad.sum())} training match(es) are not earlier than the cutoff {as_of} "
            f"(policy '{cutoff['same_day']}', mode '{cutoff['mode']}'); e.g. {shown}. "
            f"Future information must never enter training; remove them or move the cutoff.")


def fit_model(data, xi=XI, reg=REG, verbose=True, *, as_of_date=None, live=False, same_day="exclude"):
    """
    Penalised maximum-likelihood fit of:
      attack_i, defence_i, home_advantage, rho
    with exponential time decay: weight = exp(-xi * days_ago).

    reg: shrinkage strength. Adds  reg * (sum(attack^2) + sum(defence^2))
         to the negative log-likelihood, which pulls every team toward the
         league average. A team with 40 matches barely notices it; a team
         with 4 matches is pulled hard instead of getting extreme
         strengths from a handful of results. reg=0 is the old unpenalised fit.
    rho: constrained to the range that keeps the Dixon-Coles correction
         valid for every possible pairing (see rho_valid_interval).

    CUTOFF (mandatory, v2.4.1): exactly one of
      as_of_date : the prediction date (or datetime). Training matches must be earlier than it
                   (see enforce_cutoff for the same-day policy); a later/same-day match raises
                   FutureDataError. Use this for every historical prediction and backtest.
      live=True  : train the current model today (cutoff = end of today).
    There is deliberately no option that disables this check.
    """
    cutoff = _resolve_cutoff(as_of_date, live, same_day)
    enforce_cutoff(data, cutoff)          # first, before anything else, and not switch-off-able
    # v2.4: fail-closed. fit_model never repairs data - it refuses data that has not
    # passed the strict gate (see clean_matches / assert_training_data_valid).
    assert_training_data_valid(data)
    data = data.sort_values("Date").reset_index(drop=True)
    if len(data) < 2:
        raise ValueError("At least two valid played matches are required.")
    if not np.isfinite(float(xi)) or float(xi) < 0:
        raise ValueError("xi must be a finite non-negative number.")
    if not np.isfinite(float(reg)) or float(reg) < 0:
        raise ValueError("reg must be a finite non-negative number.")
    teams = sorted(set(data.HomeTeam) | set(data.AwayTeam))
    n = len(teams)
    if n < 2:
        raise ValueError("Training data must contain at least two different teams.")
    idx = {t: i for i, t in enumerate(teams)}

    home_i = data.HomeTeam.map(idx).values
    away_i = data.AwayTeam.map(idx).values
    hg = data.FTHG.values
    ag = data.FTAG.values

    days = (data.Date.max() - data.Date).dt.days.values.astype(float)
    w = np.exp(-xi * days)

    def nll(params):
        att = params[:n].copy()
        deff = params[n:2*n]
        home_adv = params[2*n]
        z = params[2*n + 1]

        att -= att.mean()                         # identifiability

        interval = rho_valid_interval(att, deff, home_adv)
        if interval is None:
            return 1e100
        rho = _rho_from_z(z, *interval)

        lam = np.exp(att[home_i] + deff[away_i] + home_adv)
        mu  = np.exp(att[away_i] + deff[home_i])
        if (not np.all(np.isfinite(lam)) or not np.all(np.isfinite(mu))
                or np.any(lam <= 0) or np.any(mu <= 0)):
            return 1e100
        t = tau_vec(hg, ag, lam, mu, rho)
        if not np.all(np.isfinite(t)) or np.any(t <= 0):
            return 1e100                          # cannot happen now; kept as a tripwire
        ll = w * (np.log(t) + poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu))
        value = -ll.sum() + reg * (np.sum(att ** 2) + np.sum((deff - deff.mean()) ** 2))   # deff mean = league goal level (intercept): NOT shrunk
        return float(value) if np.isfinite(value) else 1e100

    # starting point: rho = -0.10 (typical), expressed as z inside its valid range
    x0 = np.zeros(2*n + 2)
    x0[2*n] = 0.25          # home advantage start
    lo0, hi0 = rho_valid_interval(np.zeros(n), np.zeros(n), 0.25)
    frac = np.clip((-0.10 - lo0) / (hi0 - lo0), 0.05, 0.95)
    x0[2*n + 1] = np.log(frac / (1 - frac))

    bounds = [(None, None)] * (2*n + 1) + [(-12.0, 12.0)]

    if verbose:
        print(f"Fitting Dixon-Coles on {len(data)} matches, {n} teams (xi={xi}, reg={reg}) ...")
    res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 600, "ftol": 1e-10})

    # never build a model from a failed or non-finite optimiser result.
    if (not res.success or res.x is None or not np.all(np.isfinite(res.x))
            or not np.isfinite(res.fun) or res.fun >= 1e99):
        raise RuntimeError(
            f"Dixon-Coles optimisation failed; no model was created. Reason: {res.message}"
        )

    att = res.x[:n] - res.x[:n].mean()
    deff = res.x[n:2*n]
    home_adv = float(res.x[2*n])
    lo, hi = rho_valid_interval(att, deff, home_adv)
    rho = float(_rho_from_z(res.x[2*n + 1], lo, hi))

    counts = pd.concat([data.HomeTeam, data.AwayTeam]).value_counts()

    params = {
        "teams": teams,
        "attack": {t: float(v) for t, v in zip(teams, att)},
        "defence": {t: float(v) for t, v in zip(teams, deff)},
        "home_adv": home_adv,
        "rho": rho,
        "rho_range": [lo, hi],
        "xi": float(xi),
        "reg": float(reg),
        "n_obs": {t: int(counts.get(t, 0)) for t in teams},
        "model_version": MODEL_VERSION,
        "fitted_at": datetime.now().isoformat(timespec="seconds"),
        "data_from": str(data.Date.min().date()),
        "data_through": str(data.Date.max().date()),
        "n_matches_trained": int(len(data)),
        "as_of_date": cutoff["label"],
        "cutoff_mode": cutoff["mode"],
        "same_day_policy": cutoff["same_day"],
        "defence_mean": float(np.mean(deff)),     # kept for reference (mean of log-defences)
        "attack_prior": float(np.log(np.mean(np.exp(att)))),     # prior for a team with no data: the
        "defence_prior": float(np.log(np.mean(np.exp(deff)))),   # average team in goal terms
        "data_sha256": hashlib.sha256(pd.util.hash_pandas_object(
            data[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]], index=False).values.tobytes()).hexdigest()[:16],
    }
    enforce_cutoff(data, cutoff)                   # post-condition: the data actually used is still eligible
    worst = check_all_pairings_valid(params)       # proof, every pairing, every time

    if verbose:
        print(f"  Done.  home_adv={home_adv:.3f}   rho={rho:.3f}  "
              f"(valid range {lo:.3f}..{hi:.3f}, smallest correction factor over all pairings = {worst:.3f})")
    return params


# ============================================================
# 3. PREDICTION ENGINE
# ============================================================

def dc_corrections(lam, mu, rho):
    """The four Dixon-Coles probability corrections, each = (independent-Poisson cell) x (tau - 1):
        d00 = e^-lam e^-mu (-lam mu rho)        [0-0]
        d01 = e^-lam mu e^-mu (lam rho)         [0-1]
        d10 = lam e^-lam e^-mu (mu rho)         [1-0]
        d11 = lam e^-lam mu e^-mu (-rho)        [1-1]
    They always sum to exactly 0 (d00+d01+d10+d11 = e^-(lam+mu) rho (-lam mu + lam mu + lam mu - lam mu) = 0),
    so the correction moves probability between the four cells without creating or destroying any."""
    f0, f1 = np.exp(-lam), lam * np.exp(-lam)
    g0, g1 = np.exp(-mu), mu * np.exp(-mu)
    return (f0 * g0 * (-lam * mu * rho), f0 * g1 * (lam * rho), f1 * g0 * (mu * rho), f1 * g1 * (-rho))


def _check_dc_valid(lam, mu, rho):
    if not (np.isfinite(lam) and np.isfinite(mu) and np.isfinite(rho)) or lam <= 0 or mu <= 0:
        raise ValueError("Invalid Dixon-Coles score matrix; check lambdas and rho.")
    if min(1 - lam * mu * rho, 1 + lam * rho, 1 + mu * rho, 1 - rho) <= 0:
        raise ValueError("Invalid Dixon-Coles score matrix; a correction factor is <= 0 for this pairing.")


def score_matrix(lam, mu, rho, max_goals=MAX_GOALS):
    """
    The EXACT probability of each scoreline h-a for 0 <= h, a <= max_goals under the Dixon-Coles model:
        P[h, a] = tau(h, a) * Poisson(h; lam) * Poisson(a; mu).
    Rows = home goals, columns = away goals. Nothing is clipped and nothing is renormalised, so the grid
    does NOT sum to 1: it sums to 1 - tail, where tail = tail_probability(lam, mu, max_goals) is the
    probability that either side scores more than max_goals. (v2.4 and earlier divided by P.sum(), which
    silently spread that missing probability over the cells. That was removed in v2.4.1.)
    For 1X2 / over-under / BTTS use exact_markets(), which covers the whole distribution and does not
    depend on the grid size at all.
    """
    _check_dc_valid(lam, mu, rho)
    goals = np.arange(max_goals + 1)
    P = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))
    d00, d01, d10, d11 = dc_corrections(lam, mu, rho)
    P[0, 0] += d00
    P[0, 1] += d01
    P[1, 0] += d10
    P[1, 1] += d11
    if not np.all(np.isfinite(P)) or np.any(P < 0):
        raise ValueError("Invalid Dixon-Coles score matrix; check lambdas and rho.")
    return P


def tail_probability(lam, mu, max_goals=MAX_GOALS):
    """P(home > max_goals or away > max_goals) - exactly the probability the grid does not contain.
    (The Dixon-Coles correction lives inside the grid and sums to 0, so the tail is the independent-Poisson tail.)
    Computed from survival functions, so it stays accurate when it is tiny: a + b - a*b."""
    a = float(poisson.sf(max_goals, lam))
    b = float(poisson.sf(max_goals, mu))
    return a + b - a * b


def exact_markets(lam, mu, rho):
    """
    1X2, over/under and BTTS over the FULL (infinite) score distribution, in closed form:
      - independent part: goal difference ~ Skellam(lam, mu); total goals ~ Poisson(lam + mu); BTTS = (1-e^-lam)(1-e^-mu)
      - plus the exact Dixon-Coles corrections (dc_corrections), each assigned to the markets its cell belongs to:
            0-0 -> draw, total 0      0-1 -> away win, total 1      1-0 -> home win, total 1      1-1 -> draw, total 2, BTTS
    Because the four corrections sum to 0, the three 1X2 probabilities sum to exactly 1 and
    over + under = 1 for every line, with no grid, no truncation and no renormalisation.
    Checked in tests against a 150-goal reference grid (agreement ~1e-15) and by independent derivation.
    """
    _check_dc_valid(lam, mu, rho)
    d00, d01, d10, d11 = dc_corrections(lam, mu, rho)
    home = skellam.sf(0, lam, mu) + d10
    draw = skellam.pmf(0, lam, mu) + d00 + d11
    away = skellam.cdf(-1, lam, mu) + d01

    def total_at_most(k):                      # P(total goals <= k), full distribution
        corr = {0: d00, 1: d00 + d01 + d10}.get(k, d00 + d01 + d10 + d11)
        return float(poisson.cdf(k, lam + mu)) + corr
    over15 = 1.0 - total_at_most(1)
    over25 = 1.0 - total_at_most(2)
    over35 = 1.0 - total_at_most(3)
    btts = (1.0 - np.exp(-lam)) * (1.0 - np.exp(-mu)) + d11
    out = {"home": float(home), "draw": float(draw), "away": float(away),
           "over_1_5": float(over15), "over_2_5": float(over25), "over_3_5": float(over35),
           "under_2_5": float(total_at_most(2)), "btts_yes": float(btts), "btts_no": float(1.0 - btts)}
    if min(out.values()) < -1e-12 or max(out.values()) > 1 + 1e-12:
        raise ValueError("Invalid Dixon-Coles market probabilities; check lambdas and rho.")
    return out


def _data_age_days(data_through):
    """Days between the newest training match and today (None if unknown)."""
    try:
        return int((pd.Timestamp(datetime.now().date()) - pd.Timestamp(data_through)).days)
    except Exception:
        return None


def _resolve_team(params, team, allow_new_teams):
    """(attack, defence, is_prior_only). A team with no training data gets the
    LEAGUE-AVERAGE prior: the 'average team in goal terms', i.e. attack = ln(mean(exp(attack_i)))
    and defence = ln(mean(exp(defence_i))), so that its expected goals scored and conceded equal
    the league average. (Averaging the log-strengths instead would under-predict league goals by
    ~7-12% because exp() is convex - found by test 10.) It is NOT an estimate of the team's real
    strength and is flagged everywhere it is used."""
    if team in params["attack"]:
        return params["attack"][team], params["defence"][team], False
    if not allow_new_teams:
        sugg = difflib.get_close_matches(str(team), params["teams"], n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(sugg)}?" if sugg else ""
        raise ValueError(f"Unknown team {team!r}.{hint} Use allow_new_teams=True only if it really "
                         f"is a new team with no history (a league-average prior will be used).")
    ap = params.get("attack_prior")
    if ap is None:
        ap = float(np.log(np.mean(np.exp(list(params["attack"].values())))))
    dp = params.get("defence_prior")
    if dp is None:
        dp = float(np.log(np.mean(np.exp(list(params["defence"].values())))))
    return float(ap), float(dp), True


def _pair_rho(lam, mu, rho):
    """Clip rho into the range that keeps every Dixon-Coles factor positive for THIS
    pairing. For fitted teams rho is already inside it (guaranteed at fit time); this
    only matters for prior-only teams, whose pairings were not part of the fit check."""
    lo = max(-SAFETY / lam, -SAFETY / mu, -RHO_CAP)
    hi = min(SAFETY / (lam * mu), SAFETY, RHO_CAP)
    clipped = min(max(rho, lo), hi)
    return clipped, bool(clipped != rho)


def omitted_mass(lam, mu, max_goals=MAX_GOALS):
    """Alias of tail_probability(), kept for compatibility with v2.4 callers."""
    return tail_probability(lam, mu, max_goals)


def _lam_mu(params, home, away, allow_new_teams):
    ah, dh, new_h = _resolve_team(params, home, allow_new_teams)
    aa, da, new_a = _resolve_team(params, away, allow_new_teams)
    lam = float(np.exp(ah + da + params["home_adv"]))
    mu = float(np.exp(aa + dh))
    return lam, mu, [t for t, n in ((home, new_h), (away, new_a)) if n]


def predict(params, home, away, max_goals=MAX_GOALS, allow_new_teams=False):
    """
    Main prediction function.
    Returns a rich dict with everything useful.
    allow_new_teams=True lets a team with no training data be predicted from the
    league-average prior (clearly flagged in the result). A name that is merely
    mistyped should NOT be passed with this flag - ALEA.predict() guards that.
    """
    lam, mu, prior_only = _lam_mu(params, home, away, allow_new_teams)
    rho, rho_clipped = _pair_rho(lam, mu, params["rho"])

    P = score_matrix(lam, mu, rho, max_goals)       # exact scoreline probabilities; sums to 1 - tail
    tail = tail_probability(lam, mu, max_goals)
    mk = exact_markets(lam, mu, rho)                # FULL distribution - independent of the grid size

    p_home, p_draw, p_away = mk["home"], mk["draw"], mk["away"]
    p_over15, p_over25, p_over35 = mk["over_1_5"], mk["over_2_5"], mk["over_3_5"]
    p_under25 = mk["under_2_5"]
    p_btts_yes, p_btts_no = mk["btts_yes"], mk["btts_no"]

    # Most likely scorelines
    flat = P.ravel()
    top_idx = np.argsort(flat)[::-1][:6]
    top_scores = []
    for i in top_idx:
        h, a = divmod(i, max_goals+1)
        top_scores.append((f"{h}-{a}", float(flat[i])))

    exp_home = float(lam)
    exp_away = float(mu)
    exp_total = exp_home + exp_away

    return {
        "home": home,
        "away": away,
        "lambda_home": round(exp_home, 3),
        "lambda_away": round(exp_away, 3),
        "expected_total_goals": round(exp_total, 2),
        "p_home_win": round(float(p_home), 4),
        "p_draw":     round(float(p_draw), 4),
        "p_away_win": round(float(p_away), 4),
        "p_over_1.5": round(float(p_over15), 4),
        "p_over_2.5": round(float(p_over25), 4),
        "p_over_3.5": round(float(p_over35), 4),
        "p_under_2.5": round(float(p_under25), 4),
        "p_btts_yes": round(float(p_btts_yes), 4),
        "p_btts_no":  round(float(p_btts_no), 4),
        "most_likely_score": top_scores[0][0],
        "top_scores": top_scores,
        "rho": round(rho, 4),
        "rho_clipped_for_pair": rho_clipped,
        "markets": mk,                              # full-precision, full-distribution markets
        "tail_probability": tail,
        "p_other_scores": tail,
        "grid_sum": float(P.sum()),
        "probability_identity_error": float(abs(P.sum() + tail - 1.0)),
        "omitted_probability_mass": tail,
        "grid_warning": (f"{tail:.2e} of the probability lies outside the 0-{max_goals} score grid. It is NOT "
                         f"redistributed: the scoreline probabilities are exact and sum to {1 - tail:.10f}; "
                         f"1X2, over/under and BTTS use the full distribution and are unaffected"
                         if tail > TRUNC_WARN else None),
        "prior_only_teams": prior_only,
        "model_version": params.get("model_version"),
        "fitted_at": params.get("fitted_at"),
        "data_through": params.get("data_through"),
        "data_age_days": _data_age_days(params.get("data_through")),
        "n_obs_home": params.get("n_obs", {}).get(home, 0 if home in prior_only else None),
        "n_obs_away": params.get("n_obs", {}).get(away, 0 if away in prior_only else None),
        "matrix": P,
    }


def _predict_outcome_probs(params, home, away, max_goals=MAX_GOALS, allow_new_teams=False):
    """Lightweight version of predict() for evaluation loops - only the
    [p_home, p_draw, p_away] vector. Returns None if a team has no training data
    and allow_new_teams is False."""
    if not allow_new_teams and (home not in params["attack"] or away not in params["attack"]):
        return None
    lam, mu, _ = _lam_mu(params, home, away, allow_new_teams)
    rho, _ = _pair_rho(lam, mu, params["rho"])
    mk = exact_markets(lam, mu, rho)                # full distribution; max_goals is ignored (kept for compatibility)
    return np.array([mk["home"], mk["draw"], mk["away"]])


def pretty(pred):
    """Human-readable output."""
    print(f"\n{'='*56}")
    print(f"  {pred['home']}  vs  {pred['away']}")
    print(f"{'='*56}")
    print(f"  Expected goals   : {pred['lambda_home']}  -  {pred['lambda_away']}")
    print(f"  Expected total   : {pred['expected_total_goals']}")
    print(f"  Most likely      : {pred['most_likely_score']}")
    print()
    print(f"  Win / Draw / Lose probabilities")
    print(f"    Home win : {pred['p_home_win']:6.1%}")
    print(f"    Draw     : {pred['p_draw']:6.1%}")
    print(f"    Away win : {pred['p_away_win']:6.1%}")
    print()
    print(f"  Goals markets")
    print(f"    Over  1.5 : {pred['p_over_1.5']:6.1%}")
    print(f"    Over  2.5 : {pred['p_over_2.5']:6.1%}")
    print(f"    Over  3.5 : {pred['p_over_3.5']:6.1%}")
    print(f"    Under 2.5 : {pred['p_under_2.5']:6.1%}")
    print()
    print(f"  BTTS")
    print(f"    Yes : {pred['p_btts_yes']:6.1%}    No : {pred['p_btts_no']:6.1%}")
    print()
    print(f"  Top scorelines (exact probabilities, not renormalised)")
    for score, p in pred["top_scores"]:
        print(f"    {score:>5}   {p:6.1%}")
    if pred.get("tail_probability", 0) >= 1e-6:
        print(f"    (more than {MAX_GOALS} goals by either side: {pred['tail_probability']:.2e}; markets above include it)")
    corners = pred.get("corners")
    if corners:
        print()
        print(f"  Corners (simple weighted-average model, real HC/AC data)")
        print(f"    Expected : {corners['expected_home_corners']} - {corners['expected_away_corners']}"
              f"  (total ~{corners['expected_total_corners']})")
    print()
    print(f"  model: {pred.get('model_version','?')}  |  trained through {pred.get('data_through','?')}"
          f"  |  fitted {pred.get('fitted_at','?')}")
    print(f"{'='*56}\n")


def explain(pred):
    """
    One paragraph, plain language: what the number is, where it came
    from, and the method used - directly answers 'what's the
    probability A beats B, and why'. Adds a caution when the data is
    old or when a team has very little data behind it, because in those
    cases the number deserves less trust than it looks like it does.
    """
    text = (
        f"Based on matches through {pred.get('data_through', '?')}, each team's "
        f"expected goals come from a time-weighted Poisson model (attack "
        f"strength, defence strength, home advantage), with teams that have "
        f"few matches shrunk toward the league average. The low-scoring "
        f"cells (0-0, 1-0, 0-1, 1-1) are then corrected with the "
        f"Dixon-Coles adjustment (rho = {pred['rho']}), which adjusts "
        f"the relative probabilities of those low-scoring results. "
        f"That gives: {pred['home']} to win {pred['p_home_win']:.1%}, "
        f"draw {pred['p_draw']:.1%}, {pred['away']} to win {pred['p_away_win']:.1%}."
    )
    notes = []
    age = pred.get("data_age_days")
    if age is not None and age > STALE_DAYS:
        notes.append(f"the newest result in the data is {age} days old, so recent form is missing")
    for t in pred.get("prior_only_teams", []):
        notes.append(f"{t} has NO matches in the training data, so a league-average prior was used for it "
                     f"instead of an estimate from its own results")
    for side in ("home", "away"):
        n_obs = pred.get(f"n_obs_{side}")
        if pred[side] in pred.get("prior_only_teams", []):
            continue
        if n_obs is not None and n_obs < LOW_DATA_N:
            notes.append(f"{pred[side]} has only {n_obs} matches in the training data, so its "
                         f"estimate is uncertain")
    if notes:
        text += " Caution: " + "; ".join(notes) + "."
    return text


def strength_table(params):
    rows = []
    for t in params["teams"]:
        a = params["attack"][t]
        d = params["defence"][t]
        rows.append({"Team": t, "Attack": round(a, 3),
                     "Defence": round(d, 3), "Net": round(a - d, 3)})
    return pd.DataFrame(rows).sort_values("Net", ascending=False)


# ============================================================
# 4. CORNERS MODEL (real data, not a guessed formula)
# ============================================================

def fit_corner_rates(data, xi=XI, *, as_of_date=None, live=False, same_day="exclude"):
    """
    Simple time-weighted average corners model, built from real HC/AC
    data. Deliberately simpler than the goals model: no MLE, no tau
    correction (that correction is specific to Dixon & Coles' derivation
    for goals, not corners) - just weighted averages, the same idea
    people use for goals before upgrading to a full Dixon-Coles fit.
    Returns None if the loaded data has no HC/AC columns.
    Same mandatory cutoff as fit_model (as_of_date=... or live=True).
    """
    enforce_cutoff(data, _resolve_cutoff(as_of_date, live, same_day))
    if not {"HC", "AC"}.issubset(data.columns):
        print("  No HC/AC columns in data - corners model skipped.")
        return None

    d = data.dropna(subset=["HC", "AC"]).reset_index(drop=True)
    if d.empty:
        return None

    days = (d.Date.max() - d.Date).dt.days.values.astype(float)
    w = np.exp(-xi * days)

    league_avg = float(np.average(
        pd.concat([d.HC, d.AC]),
        weights=np.concatenate([w, w]),
    ))

    teams = sorted(set(d.HomeTeam) | set(d.AwayTeam))
    home_for, home_against, away_for, away_against = {}, {}, {}, {}
    for t in teams:
        hm = (d.HomeTeam == t).values
        am = (d.AwayTeam == t).values
        home_for[t]     = float(np.average(d.loc[hm, "HC"], weights=w[hm])) if hm.sum() else league_avg
        home_against[t] = float(np.average(d.loc[hm, "AC"], weights=w[hm])) if hm.sum() else league_avg
        away_for[t]     = float(np.average(d.loc[am, "AC"], weights=w[am])) if am.sum() else league_avg
        away_against[t] = float(np.average(d.loc[am, "HC"], weights=w[am])) if am.sum() else league_avg

    return {
        "league_avg_corners": league_avg,
        "home_for": home_for, "home_against": home_against,
        "away_for": away_for, "away_against": away_against,
    }


def predict_corners(corner_params, home, away):
    """
    Expected corners = team's own average corner-winning rate, adjusted
    by the opponent's average corner-conceding rate, centred on the
    league average (so two exactly-average teams land back on it).
    """
    if corner_params is None or home not in corner_params["home_for"] or away not in corner_params["away_for"]:
        return None
    L = corner_params["league_avg_corners"]
    exp_home = corner_params["home_for"][home] + corner_params["away_against"][away] - L
    exp_away = corner_params["away_for"][away] + corner_params["home_against"][home] - L
    exp_home = max(exp_home, 0.0)
    exp_away = max(exp_away, 0.0)
    return {
        "expected_home_corners": round(exp_home, 2),
        "expected_away_corners": round(exp_away, 2),
        "expected_total_corners": round(exp_home + exp_away, 2),
    }


# ============================================================
# 5. MARKET COMPARISON (de-vig bookmaker odds)
# ============================================================

def shin_devig(odds_home, odds_draw, odds_away):
    """
    Shin's method (Shin 1992/1993) for removing bookmaker overround.

      p_fair_i = [ sqrt(z^2 + 4(1-z) q_i^2 / S) - z ] / [ 2(1-z) ]

    where q_i = 1/odds_i (raw implied prob, NOT pre-normalised),
    S = sum(q_i) (> 1 because of the bookmaker's margin), and z is
    solved numerically so the p_fair_i sum to 1. z is Shin's estimate
    of the fraction of informed/insider money the book is pricing
    against - typically a few percent for a liquid market.

    Falls back to simple proportional de-vig (p_i = q_i / S) if the
    numerical solve fails (can happen with a very small margin).
    """
    q = np.array([1 / odds_home, 1 / odds_draw, 1 / odds_away], dtype=float)
    S = q.sum()

    def total_prob(z):
        return np.sum((np.sqrt(z**2 + 4 * (1 - z) * q**2 / S) - z) / (2 * (1 - z))) - 1

    try:
        z = brentq(total_prob, 1e-9, 0.5)
        fair = (np.sqrt(z**2 + 4 * (1 - z) * q**2 / S) - z) / (2 * (1 - z))
        fair = fair / fair.sum()
    except ValueError:
        fair = q / S
        z = None

    return {
        "p_home": float(fair[0]), "p_draw": float(fair[1]), "p_away": float(fair[2]),
        "z_insider_estimate": z,
    }


# ============================================================
# 6. EVALUATION / BACKTESTING
#    This was completely missing before. Without it there is no way
#    to know whether any prediction out of this file is any good.
# ============================================================

def _actual_outcome(hg, ag):
    """One-hot [home, draw, away] from a real result - same class order
    used everywhere else in this section."""
    if hg > ag:
        return np.array([1.0, 0.0, 0.0])
    if hg == ag:
        return np.array([0.0, 1.0, 0.0])
    return np.array([0.0, 0.0, 1.0])


def brier_score(probs, outcomes):
    """Mean squared error between predicted [pH,pD,pA] and the one-hot
    actual result, summed over classes, averaged over matches.
    0 = perfect. ~0.667 = what you'd get from guessing 1/3-1/3-1/3
    every time (the baseline to beat)."""
    return float(np.mean(np.sum((probs - outcomes) ** 2, axis=1)))


def log_loss_score(probs, outcomes):
    """-mean(log(probability the model gave to the actual outcome)).
    Punishes confident wrong predictions hard. Lower is better;
    ln(3) = 1.0986 is the uniform-guess baseline."""
    eps = 1e-12
    p_actual = np.sum(probs * outcomes, axis=1)
    return float(-np.mean(np.log(np.clip(p_actual, eps, 1.0))))


def rps_score(probs, outcomes):
    """
    Ranked Probability Score. The standard metric for football 1X2
    forecasts specifically because home/draw/away is ORDERED (away win
    < draw < home win in goal-difference terms) - RPS rewards mass
    placed close to the right answer, where Brier/log-loss treat every
    wrong class as equally wrong. 0 = perfect, 1 = worst possible.
    """
    cp = np.cumsum(probs, axis=1)
    co = np.cumsum(outcomes, axis=1)
    return float(np.mean(np.sum((cp - co) ** 2, axis=1) / (probs.shape[1] - 1)))


def calibration_table(probs, outcomes, n_bins=10):
    """
    Reliability check: every (match, outcome-class) probability gets
    bucketed, then compared to how often that class actually happened
    in that bucket. A well-calibrated model's '0.6-0.7' bucket should
    see that outcome happen 60-70% of the time.
    """
    flat_p = probs.ravel()
    flat_o = outcomes.ravel()
    bins = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (flat_p >= lo) & (flat_p < hi if i < n_bins - 1 else flat_p <= hi)
        if not mask.any():
            continue
        rows.append({
            "bucket": f"{lo:.1f}-{hi:.1f}",
            "n": int(mask.sum()),
            "predicted_avg": round(float(flat_p[mask].mean()), 3),
            "observed_freq": round(float(flat_o[mask].mean()), 3),
        })
    return pd.DataFrame(rows)


def paired_bootstrap_ci(diffs, n_boot=2000, level=0.95, seed=12345):
    """Percentile bootstrap interval for the MEAN of paired per-match differences
    (e.g. model log loss minus market log loss on the same matches). Seeded."""
    d = np.asarray(diffs, dtype=float)
    n = len(d)
    if n < 2:
        return {"mean": float(d.mean()) if n else None, "ci_low": None, "ci_high": None,
                "level": level, "n": n, "includes_zero": None}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = d[idx].mean(axis=1)
    a = (1 - level) / 2
    lo, hi = np.quantile(means, [a, 1 - a])
    return {"mean": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi),
            "level": level, "n": int(n), "includes_zero": bool(lo <= 0.0 <= hi)}


def _first_cutoff_date(dates, min_train_matches):
    """Earliest calendar date d such that at least min_train_matches matches happened BEFORE d."""
    srt = np.sort(dates.values)
    for d in np.unique(srt):
        if np.searchsorted(srt, d, side="left") >= min_train_matches:
            return pd.Timestamp(d)
    return None


def walk_forward_backtest(data, xi=XI, min_train_matches=380, step_days=14,
                          verbose=True, tune_each_fold=True, reg=REG,
                          new_teams="prior", retune_every=1):
    """
    Chronological walk-forward backtest, split by CALENDAR DATE.
    Each fold trains on every match dated BEFORE the cutoff date and predicts the
    matches dated in [cutoff, cutoff + step_days). No date is ever in both sets
    (v2.3.1 split by row count, which could put the first half of a matchday in
    training and the second half in the test fold). Hyperparameters are tuned
    inside each fold's training window only; baseline rates come from that
    window only.

    new_teams="prior": a team with no training data is predicted from the
        league-average prior and counted separately in the report;
        "skip": such matches are skipped and counted.
    NOTE: market probabilities are deliberately NOT computed here. Comparing with
    bookmaker odds needs the odds-timing alignment in aligned_market_backtest().
    """
    if new_teams not in ("prior", "skip"):
        raise ValueError("new_teams must be 'prior' or 'skip'")
    if step_days < 1:
        raise ValueError("step_days must be at least 1.")
    assert_training_data_valid(data)
    data = data.sort_values("Date").reset_index(drop=True)
    day = data["Date"].dt.normalize()
    cut = _first_cutoff_date(day, min_train_matches)
    if cut is None:
        raise ValueError("Not enough matches for this min_train_matches setting.")
    last = day.max()

    model_probs, outcomes, baseline_probs, prior_flags = [], [], [], []
    fold = n_folds_failed = n_tuning_fallback = n_skipped_unknown_team = 0
    cached = (xi, reg)
    fold_log = []
    while cut <= last:
        end = cut + pd.Timedelta(days=step_days)
        train = data[day < cut]
        test = data[(day >= cut) & (day < end)]
        if test.empty:
            cut = end
            continue
        # invariant that the whole point of date-grouping is to guarantee:
        assert train["Date"].dt.normalize().max() < test["Date"].dt.normalize().min()
        fold += 1

        fold_xi, fold_reg = cached
        if tune_each_fold and len(train) >= 100 and (fold - 1) % max(1, retune_every) == 0:
            try:
                fold_xi, fold_reg, _, failed = tune_params(train, verbose=False, as_of_date=cut)
                cached = (fold_xi, fold_reg)
                if failed and verbose:
                    print(f"  fold {fold}: {len(failed)} tuning candidate(s) failed and were skipped")
            except (ValueError, RuntimeError, FloatingPointError) as exc:
                n_tuning_fallback += 1
                if verbose:
                    print(f"  fold {fold}: tuning unavailable ({exc}); using xi={xi}, reg={reg}")
                fold_xi, fold_reg = cached = (xi, reg)
        try:
            params = fit_model(train, xi=fold_xi, reg=fold_reg, verbose=False, as_of_date=cut)
        except (ValueError, RuntimeError) as exc:
            n_folds_failed += 1                       # never hide a failed fold
            if verbose:
                print(f"  fold {fold}: FIT FAILED, fold skipped ({exc})")
            cut = end
            continue

        tr_out = np.vstack([_actual_outcome(int(r.FTHG), int(r.FTAG)) for r in train.itertuples()])
        base = np.clip(tr_out.mean(axis=0), 1e-9, 1.0)
        base /= base.sum()

        tested = 0
        for row in test.itertuples():
            is_new = row.HomeTeam not in params["attack"] or row.AwayTeam not in params["attack"]
            p = _predict_outcome_probs(params, row.HomeTeam, row.AwayTeam,
                                       allow_new_teams=(new_teams == "prior"))
            if p is None:
                n_skipped_unknown_team += 1
                continue
            model_probs.append(p)
            outcomes.append(_actual_outcome(int(row.FTHG), int(row.FTAG)))
            baseline_probs.append(base)
            prior_flags.append(is_new)
            tested += 1
        fold_log.append({"cutoff": str(cut.date()), "as_of_date_used_for_fit": str(params["as_of_date"]),
                         "n_train": int(len(train)), "n_test": int(tested),
                         "train_max_date": str(train["Date"].max().date()),
                         "test_min_date": str(test["Date"].min().date()),
                         "test_max_date": str(test["Date"].max().date())})
        if verbose:
            print(f"  fold {fold}: trained on {len(train)} (before {cut.date()}), tested on {tested}, "
                  f"xi={fold_xi}, reg={fold_reg}")
        cut = end

    if not model_probs:
        raise ValueError("Backtest produced zero predictions; check training size and team coverage.")
    model_probs = np.asarray(model_probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    baseline_probs = np.asarray(baseline_probs, dtype=float)
    prior_flags = np.asarray(prior_flags, dtype=bool)
    uniform = np.tile([1/3, 1/3, 1/3], (len(outcomes), 1))
    report = {
        "split_rule": f"calendar blocks of {step_days} days; no date appears in both training and test",
        "n_folds": int(fold),
        "fold_log": fold_log,
        "n_predictions": int(len(model_probs)),
        "n_folds_failed": int(n_folds_failed),
        "n_folds_tuning_fell_back": int(n_tuning_fallback),
        "n_skipped_team_not_in_training": int(n_skipped_unknown_team),
        "n_predictions_with_prior_only_team": int(prior_flags.sum()),
        "model_brier": brier_score(model_probs, outcomes),
        "model_log_loss": log_loss_score(model_probs, outcomes),
        "model_rps": rps_score(model_probs, outcomes),
        "baseline_uniform_brier": brier_score(uniform, outcomes),
        "baseline_uniform_log_loss": log_loss_score(uniform, outcomes),
        "baseline_uniform_rps": rps_score(uniform, outcomes),
        "baseline_train_rate_brier": brier_score(baseline_probs, outcomes),
        "baseline_train_rate_log_loss": log_loss_score(baseline_probs, outcomes),
        "baseline_train_rate_rps": rps_score(baseline_probs, outcomes),
    }
    if prior_flags.any() and (~prior_flags).any():
        k = ~prior_flags
        report["model_rps_excluding_prior_only"] = rps_score(model_probs[k], outcomes[k])
        report["model_log_loss_excluding_prior_only"] = log_loss_score(model_probs[k], outcomes[k])
    return report, model_probs, outcomes


def odds_information_date(date, rule="footballdata_weekly"):
    """
    The calendar date on which a match's odds were observed; the model may only use
    results dated STRICTLY BEFORE it when compared with those odds.

    rule="footballdata_weekly" (for Football-Data's un-suffixed 'early' odds):
        weekend fixtures (Sat/Sun/Mon) -> the preceding Friday; Friday -> same day;
        Tue/Wed/Thu -> that week's Tuesday. This reflects Football-Data's published
        collection schedule (weekend odds on Friday afternoon, midweek on Tuesday).
        It is an ASSUMPTION about their process: check it against their fixtures page.
    rule="kickoff_day" (for CLOSING odds): the match day itself; training uses only
        earlier days, which is conservative for matches kicking off later that day.
    """
    d = pd.Timestamp(date).normalize()
    if rule == "kickoff_day":
        return d
    if rule == "footballdata_weekly":
        w = d.weekday()                       # Monday = 0
        if w in (5, 6, 0):
            return d - pd.Timedelta(days=(w - 4) % 7)
        if w == 4:
            return d
        return d - pd.Timedelta(days=w - 1)   # Tue/Wed/Thu -> Tuesday
    raise ValueError(f"unknown odds timing rule: {rule!r}")


def aligned_market_backtest(data, odds_columns=("B365H", "B365D", "B365A"),
                            rule="footballdata_weekly", min_train_matches=380,
                            xi=XI, reg=REG, retune_every=8, verbose=True,
                            n_boot=2000, seed=12345):
    """
    Model vs bookmaker with matching information times.
    For every distinct odds-information date D, the model is trained ONLY on results
    dated before D and predicts every match whose odds were observed on D. Model and
    market are scored on exactly the same matches. The market probability is the
    Shin de-vigged version of the same odds. Differences (model - market) get paired
    bootstrap intervals, so 'better' is only claimed when the interval excludes zero.
    Hyperparameters are re-tuned every `retune_every` folds, on training data only.
    """
    assert_training_data_valid(data)
    missing = [c for c in odds_columns if c not in data.columns]
    if missing:
        raise ValueError(f"odds columns not in data: {missing}")
    data = data.sort_values("Date").reset_index(drop=True)
    day = data["Date"].dt.normalize()
    info = day.map(lambda d: odds_information_date(d, rule))
    oc = list(odds_columns)
    valid_odds = data[oc].apply(pd.to_numeric, errors="coerce").gt(1.0).all(axis=1)

    model_p, market_p, outs = [], [], []
    cached = (xi, reg)
    fold = n_retunes = n_fail = 0
    fold_log = []
    for D in sorted(info[valid_odds].unique()):
        train = data[day < D]
        if len(train) < min_train_matches:
            continue
        group = data[(info == D) & valid_odds]
        fold += 1
        if (fold - 1) % max(1, retune_every) == 0 and len(train) >= 100:
            try:
                bx, br, _, _ = tune_params(train, verbose=False, as_of_date=D)
                cached = (bx, br); n_retunes += 1
            except (ValueError, RuntimeError):
                pass
        try:
            params = fit_model(train, xi=cached[0], reg=cached[1], verbose=False, as_of_date=D)
        except (ValueError, RuntimeError):
            n_fail += 1
            continue
        assert train["Date"].dt.normalize().max() < D          # the alignment guarantee
        fold_log.append({"info_date": str(pd.Timestamp(D).date()), "as_of_date_used_for_fit": str(params["as_of_date"]),
                         "n_train": int(len(train)),
                         "train_max_date": str(train["Date"].max().date()), "n_scored": int(len(group))})
        for r in group.itertuples():
            pr = _predict_outcome_probs(params, r.HomeTeam, r.AwayTeam, allow_new_teams=True)
            fair = shin_devig(float(getattr(r, oc[0])), float(getattr(r, oc[1])), float(getattr(r, oc[2])))
            model_p.append(pr)
            market_p.append([fair["p_home"], fair["p_draw"], fair["p_away"]])
            outs.append(_actual_outcome(int(r.FTHG), int(r.FTAG)))
        if verbose:
            print(f"  odds date {pd.Timestamp(D).date()}: trained on {len(train)}, scored {len(group)} matches")

    if not model_p:
        raise ValueError("No matches could be scored (not enough training data or no valid odds).")
    model_p, market_p, outs = (np.asarray(x, dtype=float) for x in (model_p, market_p, outs))
    uniform = np.tile([1/3, 1/3, 1/3], (len(outs), 1))

    def metrics(pr):
        return {"brier": brier_score(pr, outs), "log_loss": log_loss_score(pr, outs), "rps": rps_score(pr, outs)}

    def per_match_ll(pr):
        return -np.log(np.clip(np.sum(pr * outs, axis=1), 1e-12, 1.0))

    def per_match_rps(pr):
        cp, co = np.cumsum(pr, axis=1), np.cumsum(outs, axis=1)
        return np.sum((cp - co) ** 2, axis=1) / (pr.shape[1] - 1)

    d_ll = paired_bootstrap_ci(per_match_ll(model_p) - per_match_ll(market_p), n_boot=n_boot, seed=seed)
    d_rps = paired_bootstrap_ci(per_match_rps(model_p) - per_match_rps(market_p), n_boot=n_boot, seed=seed)

    def verdict(ci):
        if ci["includes_zero"] is None:
            return "too few matches"
        if ci["includes_zero"]:
            return "model and market are not distinguishable on this sample"
        return "model BETTER than market" if ci["mean"] < 0 else "model WORSE than market"

    return {
        "rule": rule, "odds_columns": oc,
        "assumption": ("Training used only results dated before each odds-observation date. "
                       "Under 'footballdata_weekly' that date is inferred from the weekday (see "
                       "odds_information_date) - verify against the source's collection schedule."),
        "n_matches_scored": int(len(outs)), "n_folds": fold, "n_retunes": n_retunes, "n_fit_failures": n_fail,
        "fold_log": fold_log,
        "model": metrics(model_p), "market": metrics(market_p), "uniform": metrics(uniform),
        "model_minus_market_log_loss": d_ll, "model_minus_market_rps": d_rps,
        "verdict_log_loss": verdict(d_ll), "verdict_rps": verdict(d_rps),
        "note": "Negative differences favour the model. Same matches, same information time. Sample size matters: "
                "a few hundred matches rarely separates a model from the market.",
    }, model_p, market_p, outs


def tune_params(data, xi_candidates=None, reg_candidates=None, valid_frac=0.2, verbose=True, *,
                as_of_date=None, live=False, same_day="exclude"):
    """
    Pick the time-decay rate (xi) AND the shrinkage strength (reg) from
    validation performance instead of guessing. Chronological split only
    (see walk_forward_backtest docstring for why): fit on the first part,
    score log loss on the held-out tail, keep the best pair.

    A candidate that fails (optimiser error, invalid fit) is SKIPPED and
    reported, not allowed to abort the whole tuning - that was what forced
    the old xi=0.005 fallback in three backtest folds.
    Returns (best_xi, best_reg, results, failed):
      results = [(xi, reg, log_loss), ...] for candidates that worked
      failed  = [(xi, reg, reason), ...]   for candidates that did not
    The same mandatory cutoff as fit_model applies to `data` (as_of_date=... or live=True), and
    every inner fit uses the validation block's start date as ITS cutoff.
    """
    enforce_cutoff(data, _resolve_cutoff(as_of_date, live, same_day))
    if xi_candidates is None:
        xi_candidates = [0.0, 0.001, 0.0018, 0.003, 0.005]
    if reg_candidates is None:
        reg_candidates = [0.0, 1.0, 3.0, 8.0]
    data = data.sort_values("Date").reset_index(drop=True)
    if not 0 < valid_frac < 0.5:
        raise ValueError("valid_frac must be between 0 and 0.5.")
    # split by CALENDAR DATE: the validation block starts on the first date at/after the
    # (1 - valid_frac) position, and no date is shared with the training block.
    day = data["Date"].dt.normalize()
    cut_date = day.iloc[min(int(len(data) * (1 - valid_frac)), len(data) - 1)]
    train, valid = data[day < cut_date], data[day >= cut_date]
    if len(train) < 50 or valid.empty:
        raise ValueError("Not enough data for a chronological validation split.")

    results, failed = [], []
    for xi in xi_candidates:
        for reg in reg_candidates:
            try:
                params = fit_model(train, xi=xi, reg=reg, verbose=False, as_of_date=cut_date)
                probs, outcomes = [], []
                for _, row in valid.iterrows():
                    p = _predict_outcome_probs(params, row.HomeTeam, row.AwayTeam)
                    if p is None:
                        continue
                    probs.append(p)
                    outcomes.append(_actual_outcome(int(row.FTHG), int(row.FTAG)))
                if not probs:
                    raise ValueError("no validation predictions")
                ll = log_loss_score(np.asarray(probs), np.asarray(outcomes))
                if not np.isfinite(ll):
                    raise ValueError("non-finite log loss")
                results.append((float(xi), float(reg), float(ll)))
            except (ValueError, RuntimeError, FloatingPointError) as exc:
                failed.append((float(xi), float(reg), str(exc)))

    if not results:
        raise ValueError(f"tuning failed: all {len(failed)} candidates failed "
                         f"(first reason: {failed[0][2] if failed else 'n/a'})")
    results.sort(key=lambda r: r[2])
    best_xi, best_reg, _ = results[0]

    if verbose:
        print("  tuning on a chronological validation split (lower log loss = better):")
        for xi, reg, ll in sorted(results, key=lambda r: r[2])[:6]:
            flag = "  <- best" if (xi, reg) == (best_xi, best_reg) else ""
            print(f"    xi={xi:<7} reg={reg:<4} log_loss={ll:.4f}{flag}")
        if failed:
            print(f"    ({len(failed)} of {len(results) + len(failed)} candidates failed and were skipped)")
    return best_xi, best_reg, results, failed


def tune_xi(data, candidates=None, valid_frac=0.2, verbose=True, reg=REG, **cutoff):
    """Backward-compatible wrapper: tune xi only, at a fixed reg (pass as_of_date=... or live=True).
    Returns (best_xi, [(xi, log_loss), ...])."""
    best_xi, _, results, _ = tune_params(
        data, xi_candidates=candidates, reg_candidates=[reg],
        valid_frac=valid_frac, verbose=verbose, **cutoff)
    return best_xi, [(xi, ll) for xi, _, ll in results]


# ============================================================
# 7. PERSISTENCE
# ============================================================

class ModelVersionError(ValueError):
    """A saved model was written by a different model version than the one loading it."""


def default_model_path(version=MODEL_VERSION, directory="."):
    """One file per model version, so v2.3.1 and v2.4 parameters can never overwrite each other."""
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(version))
    return os.path.join(directory, f"alea_model_{safe}.json")


def save_model(params, path=None, directory="."):
    """Save a fitted model, by default to alea_model_<its own version>.json. The write is
    atomic (temp file then rename), so a crash can't leave a half-written model."""
    path = path or default_model_path(params.get("model_version", MODEL_VERSION), directory)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(params, f, indent=2)
    os.replace(tmp, path)
    print(f"  Saved model ({params.get('model_version')}, fitted {params.get('fitted_at')}, "
          f"data {params.get('data_sha256')}) to {path}")
    return path


_REQUIRED_MODEL_KEYS = ("teams", "attack", "defence", "home_adv", "rho", "model_version")


def load_model(path=None, expected_version=MODEL_VERSION, allow_version_mismatch=False, directory="."):
    """Load a saved model. By default only the file for THIS code's version is accepted:
    a model written by another version raises ModelVersionError unless you explicitly
    pass allow_version_mismatch=True. The mathematical validity of every pairing is
    re-checked on load."""
    path = path or default_model_path(expected_version, directory)
    with open(path) as f:
        params = json.load(f)
    missing = [k for k in _REQUIRED_MODEL_KEYS if k not in params]
    if missing:
        raise ValueError(f"{path} is not a valid ALEA model file (missing {missing}).")
    if params["model_version"] != expected_version and not allow_version_mismatch:
        raise ModelVersionError(
            f"{path} was written by {params['model_version']!r} but this code is {expected_version!r}. "
            f"Refusing to mix versions; pass allow_version_mismatch=True only if you know what you are doing.")
    check_all_pairings_valid(params)
    print(f"  Loaded model {params.get('model_version')}, fitted {params.get('fitted_at')}, "
          f"trained on {params.get('n_matches_trained')} matches through {params.get('data_through')}")
    return params


# ============================================================
# 8. SIMPLE PUBLIC API
# ============================================================

class ALEA:
    """
    One-liner interface.

    source="openfootball" (default): no API key, free, auto-updated
      daily, and the only one of the two sources that also hands you
      each season's still-unplayed fixtures - so self.fixtures gets
      populated and .upcoming() works. No corners/odds columns though,
      so self.corner_params and the backtest's market comparison will
      both come back empty (they degrade gracefully, not an error).
    source="footballdata": football-data.co.uk, gives you corners and
      bookmaker odds (so the corners model and market comparison both
      work), but it's a pure historical-results archive - no upcoming
      fixtures, so self.fixtures stays empty and .upcoming() has
      nothing to predict.
    """

    def __init__(self, data=None, fixtures=None, source="openfootball",
                 seasons=None, league="en.1", xi=None, reg=None, auto_tune_xi=True, as_of_date=None):
        if data is None:
            if source == "openfootball":
                seasons = seasons or ("2024-25", "2025-26", "2026-27")
                print(f"Loading from openfootball ({league}, seasons {seasons}) ...")
                data, fixtures = load_from_openfootball(seasons=seasons, league=league)
            elif source == "footballdata":
                print("Loading from football-data.co.uk ...")
                data = load_from_csv()
                fixtures = None
            else:
                raise ValueError(f"Unknown source: {source!r} (use 'openfootball' or 'footballdata')")
        # v2.4: every input - loader output or a DataFrame you pass in - goes through the same strict gate.
        attrs = dict(getattr(data, "attrs", {}))
        self.data, self.cleaning_report = clean_matches(data)
        self.data.attrs.update(attrs)
        if fixtures is not None and not fixtures.empty:
            fixtures = fixtures.copy()
            fixtures["HomeTeam"] = fixtures["HomeTeam"].map(_team_name)
            fixtures["AwayTeam"] = fixtures["AwayTeam"].map(_team_name)
        self.fixtures = fixtures
        data = self.data
        self.freshness = data.attrs.get("freshness")
        # v2.4.1 cutoff: as_of_date=None -> train the CURRENT model (live). as_of_date=X -> a historical
        # model as it would have been on X: only matches dated strictly before X are used (the count
        # excluded is printed), and fit_model re-verifies it.
        self.as_of_date = as_of_date
        if as_of_date is None:
            self._cut = {"live": True}
        else:
            self._cut = {"as_of_date": as_of_date}
            cutoff = _resolve_cutoff(as_of_date, False, "exclude")
            eligible = data[data["Date"].dt.normalize() < cutoff["as_of"].normalize()].copy()
            eligible.attrs.update(data.attrs)
            print(f"  Historical model as of {cutoff['label']}: using {len(eligible)} matches dated before it; "
                  f"{len(data) - len(eligible)} later match(es) excluded from training.")
            self.data = data = eligible
        # every team name the data SOURCE knows about (played matches + fixtures). A team in this
        # list but absent from training data is a genuine new team; a name in neither is a typo.
        self.known_teams = set(data.HomeTeam) | set(data.AwayTeam)
        if fixtures is not None and not fixtures.empty:
            self.known_teams |= set(fixtures.HomeTeam.dropna()) | set(fixtures.AwayTeam.dropna())

        if xi is None and reg is None and auto_tune_xi:
            print("\nTuning xi (time-decay) and reg (shrinkage) on a validation split ...")
            xi, reg, _, _ = tune_params(data, **self._cut)
        else:
            xi = XI if xi is None else xi
            reg = REG if reg is None else reg

        self.xi, self.reg = xi, reg
        self.params = fit_model(data, xi=xi, reg=reg, **self._cut)
        self.corner_params = fit_corner_rates(data, xi=xi, **self._cut)

    def status(self):
        """What data is this model actually built on, and is it current?"""
        pr = self.params
        print(f"  model {pr['model_version']}  |  {pr['n_matches_trained']} matches, "
              f"{pr['data_from']} -> {pr['data_through']}  |  xi={pr['xi']}  reg={pr['reg']}")
        fr = self.freshness
        if fr is None:
            print("  freshness: not checked for this data source")
        elif fr["warnings"]:
            for w in fr["warnings"]:
                print(f"  WARNING: {w}")
        else:
            print(f"  freshness OK (newest result {fr['newest_result']})")
        low = {t: n for t, n in pr["n_obs"].items() if n < LOW_DATA_N}
        if low:
            print(f"  low-data teams (< {LOW_DATA_N} matches, predictions uncertain): {low}")

    def predict(self, home, away):
        """Known teams: normal prediction. A team the data source lists but the model has no
        training matches for (e.g. newly promoted): league-average prior, clearly flagged.
        A name the source has never heard of (probably a typo): ValueError with suggestions."""
        home, away = _team_name(home), _team_name(away)
        for t in (home, away):
            if t not in self.params["attack"] and t not in self.known_teams:
                _resolve_team(self.params, t, allow_new_teams=False)      # raises with suggestions
        pred = predict(self.params, home, away, allow_new_teams=True)
        pred["corners"] = predict_corners(self.corner_params, home, away)
        return pred

    def show(self, home, away):
        p = self.predict(home, away)
        pretty(p)
        return p

    def explain(self, home, away):
        """Predict + the plain-language 'why' paragraph, printed."""
        p = self.predict(home, away)
        print(explain(p))
        return p

    def upcoming(self, n=10, team=None):
        """
        Predict the next n real, dated fixtures still to be played -
        only available when loaded with source="openfootball" (the
        default), since that's the only source that carries them.
        Pass team="..." to filter to one team's fixtures.
        """
        if self.fixtures is None or self.fixtures.empty:
            print("No upcoming-fixture data loaded "
                  "(only available with source='openfootball').")
            return []

        # FIX 6: only dates today or later can appear in upcoming().
        fx = self.fixtures.copy()
        fx["Date"] = pd.to_datetime(fx["Date"], errors="coerce")
        fx = fx.dropna(subset=["Date"])
        fx = fx[fx["Date"].dt.normalize() >= pd.Timestamp(datetime.now().date())]
        fx = fx.sort_values("Date")
        if team:
            fx = fx[(fx.HomeTeam == team) | (fx.AwayTeam == team)]

        results, shown = [], 0
        for _, row in fx.iterrows():
            if shown >= n:
                break
            try:
                pred = self.predict(row.HomeTeam, row.AwayTeam)
            except ValueError:
                continue   # a team not seen enough in training data yet
            pred["fixture_date"] = str(row.Date.date())
            print(f"\n{row.Date.date()}  {row.HomeTeam} vs {row.AwayTeam}")
            print(explain(pred))
            results.append(pred)
            shown += 1

        if shown == 0:
            print("No upcoming fixtures found for teams the model has trained on.")
        return results

    def table(self):
        return strength_table(self.params)

    def backtest(self, min_train_matches=380, step_days=14, new_teams="prior", retune_every=1):
        report, probs, outcomes = walk_forward_backtest(
            self.data, xi=self.xi, reg=self.reg, min_train_matches=min_train_matches,
            step_days=step_days, new_teams=new_teams, retune_every=retune_every)
        print("\nBacktest report:")
        for k, v in report.items():
            print(f"  {k}: {v}")
        print("\nCalibration:")
        print(calibration_table(probs, outcomes).to_string(index=False))
        return report

    def aligned_backtest(self, closing=False, min_train_matches=380, retune_every=8):
        """Model vs bookmaker with matching information times (needs odds columns, i.e.
        source='footballdata'). closing=True uses the closing-odds columns (B365CH/CD/CA)."""
        cols = ("B365CH", "B365CD", "B365CA") if closing else ("B365H", "B365D", "B365A")
        rule = "kickoff_day" if closing else "footballdata_weekly"
        report, *_ = aligned_market_backtest(self.data, odds_columns=cols, rule=rule,
                                             min_train_matches=min_train_matches, xi=self.xi,
                                             reg=self.reg, retune_every=retune_every)
        print("\nAligned market comparison:")
        for k, v in report.items():
            print(f"  {k}: {v}")
        return report

    def save(self, path=None):
        """Saves to alea_model_<version>.json unless you give a path."""
        return save_model(self.params, path)


# ============================================================
# 9. RUN
# ============================================================

if __name__ == "__main__":
    print(DISCLAIMER)

    model = ALEA()   # source="openfootball" by default: no key, free,
                      # loads 2024-25/2025-26/2026-27 + upcoming fixtures

    print("\nCurrent strength ranking:")
    print(model.table().to_string(index=False))

    print("\nRunning walk-forward backtest (this is the step that tells you if the model is any good) ...")
    model.backtest()

    print("\nNext real, dated fixtures:")
    model.upcoming(5)

    model.save()

