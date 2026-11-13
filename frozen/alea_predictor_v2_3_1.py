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
import requests
import numpy as np
import pandas as pd
from scipy.optimize import minimize, brentq
from scipy.stats import poisson
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")


# ============================================================
# CONFIG
# ============================================================

API_KEY  = os.environ.get("FOOTBALL_API_KEY")   # set this in your shell - never hardcode a real key here
API_BASE = "https://footballapi.org"             # change when you have working docs

MAX_GOALS     = 8        # scoreline grid 0..8
XI            = 0.0018   # fallback time-decay if you don't run tune_params()
REG           = 1.0      # fallback shrinkage strength (0 = none) if you don't run tune_params()
RHO_CAP       = 0.3      # |rho| never above this (typical fitted values are around -0.1)
SAFETY        = 0.98     # every Dixon-Coles correction factor stays >= 1-SAFETY (= 0.02) > 0
LOW_DATA_N    = 10       # fewer than this many training matches for a team = flagged in explain()
STALE_DAYS    = 14       # newest result older than this = data-freshness warning
MODEL_VERSION = "alea-dc-v2.3.1"
DISCLAIMER    = "Model output only - probabilities, not certainties. No betting advice, no guaranteed edge."


# ============================================================
# 1. DATA
# ============================================================

CORE_COLS  = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]
EXTRA_COLS = ["HC", "AC", "B365H", "B365D", "B365A"]   # optional - kept when present, skipped when not


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
    data = data[keep].dropna(subset=CORE_COLS)
    data["Date"] = pd.to_datetime(data["Date"], dayfirst=True, errors="coerce")
    data = data.dropna(subset=["Date", "FTHG", "FTAG"])
    data["FTHG"] = data["FTHG"].astype(int)
    data["FTAG"] = data["FTAG"].astype(int)
    data["HomeTeam"] = data["HomeTeam"].map(_team_name)
    data["AwayTeam"] = data["AwayTeam"].map(_team_name)
    data = data.sort_values("Date").reset_index(drop=True)

    if missing_extra:
        print(f"  Note: columns not in this data, related features will be skipped: {missing_extra}")
    print(f"Total: {len(data)} matches  ({data.Date.min().date()} -> {data.Date.max().date()})")

    validate_data(data)
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
    data = data.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    print(f"Total: {len(data)} played matches ({data.Date.min().date()} -> {data.Date.max().date()})")
    validate_data(data)

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


def fit_model(data, xi=XI, reg=REG, verbose=True):
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
    """
    # validate inputs before starting numerical optimisation.
    required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"Training data missing columns: {sorted(missing)}")
    data = data.dropna(subset=list(required)).copy()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
    if len(data) < 2:
        raise ValueError("At least two valid played matches are required.")
    if (data[["FTHG", "FTAG"]] < 0).any().any():
        raise ValueError("Training data contains negative goal counts.")
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
    }
    worst = check_all_pairings_valid(params)       # proof, every pairing, every time

    if verbose:
        print(f"  Done.  home_adv={home_adv:.3f}   rho={rho:.3f}  "
              f"(valid range {lo:.3f}..{hi:.3f}, smallest correction factor over all pairings = {worst:.3f})")
    return params


# ============================================================
# 3. PREDICTION ENGINE
# ============================================================

def score_matrix(lam, mu, rho, max_goals=MAX_GOALS):
    """Full P(home=h, away=a) matrix with Dixon-Coles tau, normalised."""
    goals = np.arange(max_goals + 1)
    P = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))

    # apply tau only on the four low-score cells
    P[0, 0] *= (1 - lam * mu * rho)
    P[0, 1] *= (1 + lam * rho)
    P[1, 0] *= (1 + mu * rho)
    P[1, 1] *= (1 - rho)

    # FIX 4: reject invalid score matrices instead of concealing them.
    if not np.all(np.isfinite(P)) or np.any(P < 0) or P.sum() <= 0:
        raise ValueError("Invalid Dixon-Coles score matrix; check lambdas and rho.")
    P = np.clip(P, 0, None)
    P /= P.sum()
    return P


def _data_age_days(data_through):
    """Days between the newest training match and today (None if unknown)."""
    try:
        return int((pd.Timestamp(datetime.now().date()) - pd.Timestamp(data_through)).days)
    except Exception:
        return None


def predict(params, home, away, max_goals=MAX_GOALS):
    """
    Main prediction function.
    Returns a rich dict with everything useful.
    """
    if home not in params["attack"] or away not in params["attack"]:
        missing = [t for t in (home, away) if t not in params["attack"]]
        raise ValueError(f"Unknown team(s): {missing}")

    att, deff = params["attack"], params["defence"]
    home_adv, rho = params["home_adv"], params["rho"]

    lam = np.exp(att[home] + deff[away] + home_adv)
    mu  = np.exp(att[away] + deff[home])

    P = score_matrix(lam, mu, rho, max_goals)

    # 1X2
    p_home = np.tril(P, -1).sum()
    p_draw = np.trace(P)
    p_away = np.triu(P,  1).sum()

    # Over / Under
    totals = np.add.outer(np.arange(max_goals+1), np.arange(max_goals+1))
    p_over25  = P[totals > 2.5].sum()
    p_under25 = P[totals < 2.5].sum()
    p_over15  = P[totals > 1.5].sum()
    p_over35  = P[totals > 3.5].sum()

    # BTTS
    p_btts_yes = P[1:, 1:].sum()
    p_btts_no  = 1 - p_btts_yes

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
        "model_version": params.get("model_version"),
        "fitted_at": params.get("fitted_at"),
        "data_through": params.get("data_through"),
        "data_age_days": _data_age_days(params.get("data_through")),
        "n_obs_home": params.get("n_obs", {}).get(home),
        "n_obs_away": params.get("n_obs", {}).get(away),
        "matrix": P,
    }


def _predict_outcome_probs(params, home, away, max_goals=MAX_GOALS):
    """Lightweight version of predict() for evaluation loops - only the
    [p_home, p_draw, p_away] vector, skips everything else for speed.
    Returns None if either team wasn't in the training data."""
    if home not in params["attack"] or away not in params["attack"]:
        return None
    att, deff = params["attack"], params["defence"]
    home_adv, rho = params["home_adv"], params["rho"]
    lam = np.exp(att[home] + deff[away] + home_adv)
    mu = np.exp(att[away] + deff[home])
    P = score_matrix(lam, mu, rho, max_goals)
    return np.array([np.tril(P, -1).sum(), np.trace(P), np.triu(P, 1).sum()])


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
    print(f"  Top scorelines")
    for score, p in pred["top_scores"]:
        print(f"    {score:>5}   {p:6.1%}")
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
    for side in ("home", "away"):
        n_obs = pred.get(f"n_obs_{side}")
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

def fit_corner_rates(data, xi=XI):
    """
    Simple time-weighted average corners model, built from real HC/AC
    data. Deliberately simpler than the goals model: no MLE, no tau
    correction (that correction is specific to Dixon & Coles' derivation
    for goals, not corners) - just weighted averages, the same idea
    people use for goals before upgrading to a full Dixon-Coles fit.
    Returns None if the loaded data has no HC/AC columns.
    """
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


def walk_forward_backtest(data, xi=XI, min_train_matches=380, step=40,
                          verbose=True, tune_each_fold=True, reg=REG):
    """
    Chronological walk-forward backtest.
    FIX 3: xi tuning occurs inside each fold's training data only.
    FIX 5: baseline rates come from that fold's training outcomes only.
    """
    data = data.sort_values("Date").reset_index(drop=True)
    n = len(data)
    if n < min_train_matches + 1:
        raise ValueError("Not enough matches for this min_train_matches setting.")
    if step < 1:
        raise ValueError("step must be at least 1.")

    has_odds = {"B365H", "B365D", "B365A"}.issubset(data.columns)
    model_probs, market_probs, outcomes, baseline_probs = [], [], [], []
    cutoff, fold = min_train_matches, 0
    n_folds_failed = n_tuning_fallback = n_skipped_unknown_team = 0

    while cutoff < n:
        train = data.iloc[:cutoff].copy()
        test = data.iloc[cutoff:cutoff + step]
        if test.empty:
            break

        fold_xi, fold_reg = xi, reg
        if tune_each_fold and len(train) >= 100:
            try:
                fold_xi, fold_reg, _, failed = tune_params(train, verbose=False)
                if failed and verbose:
                    print(f"  fold {fold + 1}: {len(failed)} tuning candidate(s) failed and were skipped")
            except (ValueError, RuntimeError, FloatingPointError) as exc:
                n_tuning_fallback += 1
                if verbose:
                    print(f"  fold {fold + 1}: tuning unavailable ({exc}); using xi={xi}, reg={reg}")
                fold_xi, fold_reg = xi, reg
        try:
            params = fit_model(train, xi=fold_xi, reg=fold_reg, verbose=False)
        except (ValueError, RuntimeError) as exc:
            # never hide a failed fold, never let it poison the metrics
            n_folds_failed += 1
            fold += 1
            if verbose:
                print(f"  fold {fold}: FIT FAILED, fold skipped ({exc})")
            cutoff += step
            continue

        train_outcomes = np.vstack([
            _actual_outcome(int(row.FTHG), int(row.FTAG))
            for _, row in train.iterrows()
        ])
        base = train_outcomes.mean(axis=0)
        base = np.clip(base, 1e-9, 1.0)
        base /= base.sum()

        tested = 0
        for _, row in test.iterrows():
            p = _predict_outcome_probs(params, row.HomeTeam, row.AwayTeam)
            if p is None:
                n_skipped_unknown_team += 1
                continue
            model_probs.append(p)
            outcomes.append(_actual_outcome(int(row.FTHG), int(row.FTAG)))
            baseline_probs.append(base)
            if (has_odds and all(pd.notna(row.get(c)) for c in ("B365H", "B365D", "B365A"))
                    and all(float(row.get(c)) > 1 for c in ("B365H", "B365D", "B365A"))):
                fair = shin_devig(row.B365H, row.B365D, row.B365A)
                market_probs.append([fair["p_home"], fair["p_draw"], fair["p_away"]])
            else:
                market_probs.append(None)
            tested += 1

        fold += 1
        if verbose:
            print(f"  fold {fold}: trained on {cutoff}, tested on {tested}, xi={fold_xi}, reg={fold_reg}")
        cutoff += step

    if not model_probs:
        raise ValueError("Backtest produced zero predictions; check training size and team coverage.")
    model_probs = np.asarray(model_probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    baseline_probs = np.asarray(baseline_probs, dtype=float)
    uniform = np.tile([1/3, 1/3, 1/3], (len(outcomes), 1))
    report = {
        "n_predictions": int(len(model_probs)),
        "n_folds_failed": int(n_folds_failed),
        "n_folds_tuning_fell_back": int(n_tuning_fallback),
        "n_skipped_team_not_in_training": int(n_skipped_unknown_team),
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
    has_market = np.array([m is not None for m in market_probs], dtype=bool)
    if has_market.any():
        market = np.asarray([m for m in market_probs if m is not None], dtype=float)
        market_outcomes = outcomes[has_market]
        report["market_brier"] = brier_score(market, market_outcomes)
        report["market_log_loss"] = log_loss_score(market, market_outcomes)
        report["market_rps"] = rps_score(market, market_outcomes)
        report["n_with_market_odds"] = int(has_market.sum())
    return report, model_probs, outcomes


def tune_params(data, xi_candidates=None, reg_candidates=None, valid_frac=0.2, verbose=True):
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
    """
    if xi_candidates is None:
        xi_candidates = [0.0, 0.001, 0.0018, 0.003, 0.005]
    if reg_candidates is None:
        reg_candidates = [0.0, 1.0, 3.0, 8.0]
    data = data.sort_values("Date").reset_index(drop=True)
    if not 0 < valid_frac < 0.5:
        raise ValueError("valid_frac must be between 0 and 0.5.")
    cut = int(len(data) * (1 - valid_frac))
    train, valid = data.iloc[:cut], data.iloc[cut:]
    if len(train) < 50 or valid.empty:
        raise ValueError("Not enough data for a chronological validation split.")

    results, failed = [], []
    for xi in xi_candidates:
        for reg in reg_candidates:
            try:
                params = fit_model(train, xi=xi, reg=reg, verbose=False)
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


def tune_xi(data, candidates=None, valid_frac=0.2, verbose=True, reg=REG):
    """Backward-compatible wrapper: tune xi only, at a fixed reg.
    Returns (best_xi, [(xi, log_loss), ...])."""
    best_xi, _, results, _ = tune_params(
        data, xi_candidates=candidates, reg_candidates=[reg],
        valid_frac=valid_frac, verbose=verbose)
    return best_xi, [(xi, ll) for xi, _, ll in results]


# ============================================================
# 7. PERSISTENCE
# ============================================================

def save_model(params, path="alea_model.json"):
    """Save a fitted model to disk, versioning included, so you don't
    need to refit from scratch every run and can trace any saved
    prediction back to exactly what produced it."""
    with open(path, "w") as f:
        json.dump(params, f, indent=2)
    print(f"  Saved model ({params.get('model_version')}, fitted {params.get('fitted_at')}) to {path}")


def load_model(path="alea_model.json"):
    with open(path) as f:
        params = json.load(f)
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
                 seasons=None, league="en.1", xi=None, reg=None, auto_tune_xi=True):
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
        # FIX 2: apply canonical names consistently to every input source.
        self.data = data.copy()
        self.data["HomeTeam"] = self.data["HomeTeam"].map(_team_name)
        self.data["AwayTeam"] = self.data["AwayTeam"].map(_team_name)
        if fixtures is not None and not fixtures.empty:
            fixtures = fixtures.copy()
            fixtures["HomeTeam"] = fixtures["HomeTeam"].map(_team_name)
            fixtures["AwayTeam"] = fixtures["AwayTeam"].map(_team_name)
        self.fixtures = fixtures
        data = self.data
        self.freshness = data.attrs.get("freshness")

        if xi is None and reg is None and auto_tune_xi:
            print("\nTuning xi (time-decay) and reg (shrinkage) on a validation split ...")
            xi, reg, _, _ = tune_params(data)
        else:
            xi = XI if xi is None else xi
            reg = REG if reg is None else reg

        self.xi, self.reg = xi, reg
        self.params = fit_model(data, xi=xi, reg=reg)
        self.corner_params = fit_corner_rates(data, xi=xi)

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
        pred = predict(self.params, home, away)
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

    def backtest(self, min_train_matches=380, step=40):
        report, probs, outcomes = walk_forward_backtest(
            self.data, xi=self.xi, reg=self.reg,
            min_train_matches=min_train_matches, step=step
        )
        print("\nBacktest report:")
        for k, v in report.items():
            print(f"  {k}: {v}")
        print("\nCalibration:")
        print(calibration_table(probs, outcomes).to_string(index=False))
        return report

    def save(self, path="alea_model.json"):
        save_model(self.params, path)


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

