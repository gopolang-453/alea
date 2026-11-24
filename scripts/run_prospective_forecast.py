#!/usr/bin/env python3
"""Stage 9 prospective forecasts: freeze pre-kickoff probabilities in the ledger.

Pipeline (fails closed at every gate):
 1. Load historical OpenFootball seasons from ``data/raw/openfootball``.
 2. Load current-season results from a local football-data.co.uk CSV
    (``--results-csv``). That source has no stated licence, so this script
    only reads a local copy; raw data is never written to ``results/``.
 3. Load current-season fixtures (with kickoff times) from the OpenFootball
    season JSON (``--fixtures-json``).
 4. Gates:
    - Completeness: every fixture whose kickoff is more than ``--grace-hours``
      in the past must have a result (otherwise the results feed is stale).
    - Freshness: Stage 12 ``data_freshness`` on the latest result.
    - Cross-check: results present in both feeds must agree exactly.
 5. Fit the frozen champion (v2.4.1, fixed xi/reg) on results with kickoff
    strictly before ``--now`` and forecast fixtures in ``(now, now + horizon]``.
 6. Append forecasts to the ledger; existing forecasts are never overwritten.
    Completed fixtures already in the ledger get their outcomes settled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_openfootball import parse_openfootball_file  # noqa: E402
from scripts.run_stage9_mle_backtest import _coerce_goals, load_model_module  # noqa: E402
from stages.stage1.data_store import canonical_team, parse_match_dates  # noqa: E402
from stages.stage12.reliability import data_freshness, sha256_file  # noqa: E402
from stages.stage9.prospective_ledger import ProspectiveLedger  # noqa: E402

LONDON = ZoneInfo("Europe/London")
HISTORICAL_SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
MATCH_DURATION = timedelta(hours=2)


class GateError(RuntimeError):
    pass


def fixture_key(kickoff_utc: datetime, home: str, away: str) -> str:
    return f"{kickoff_utc.astimezone(LONDON).date().isoformat()}|{home}|{away}"


def _london_to_utc(date_str: str, time_str: str | None) -> datetime:
    time_str = time_str or "15:00"
    local = datetime.fromisoformat(f"{date_str}T{time_str[:5]}").replace(tzinfo=LONDON)
    return local.astimezone(timezone.utc)


def load_fixtures(path: Path) -> pd.DataFrame:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for match in document["matches"]:
        rows.append({
            "kickoff_utc": _london_to_utc(match["date"], match.get("time")),
            "home": canonical_team(match["team1"]),
            "away": canonical_team(match["team2"]),
        })
    frame = pd.DataFrame(rows)
    if frame.duplicated(["home", "away"]).any():
        raise GateError("fixture list repeats a home/away pairing")
    return frame


def load_openfootball_results(path: Path, season: str) -> pd.DataFrame:
    """Completed matches from an OpenFootball season file, with kickoff in UTC."""
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for match in document["matches"]:
        score = match.get("score")
        if isinstance(score, list):
            score = {"ft": score}
        if not score or not score.get("ft"):
            continue
        rows.append({
            "kickoff_utc": _london_to_utc(match["date"], match.get("time")),
            "home": canonical_team(match["team1"]),
            "away": canonical_team(match["team2"]),
            "FTHG": int(score["ft"][0]),
            "FTAG": int(score["ft"][1]),
        })
    return pd.DataFrame(rows, columns=["kickoff_utc", "home", "away", "FTHG", "FTAG"])


def load_results_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    if missing := required - set(raw.columns):
        raise GateError(f"results CSV missing columns {sorted(missing)}")
    raw = raw.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    dates = parse_match_dates(raw["Date"])
    times = raw["Time"].fillna("15:00") if "Time" in raw.columns else pd.Series("15:00", index=raw.index)
    rows = []
    for (idx, row), day, time_str in zip(raw.iterrows(), dates, times):
        rows.append({
            "kickoff_utc": _london_to_utc(day.date().isoformat(), str(time_str)),
            "home": canonical_team(row["HomeTeam"]),
            "away": canonical_team(row["AwayTeam"]),
            "FTHG": int(row["FTHG"]),
            "FTAG": int(row["FTAG"]),
        })
    frame = pd.DataFrame(rows)
    if frame.duplicated(["home", "away"]).any():
        raise GateError("results CSV repeats a home/away pairing")
    return frame


def run_gates(fixtures, current, openfootball_current, now, *, grace_hours, max_age_hours):
    report = {}
    played = set(zip(current.home, current.away))
    due = fixtures[fixtures.kickoff_utc + MATCH_DURATION + timedelta(hours=grace_hours) < now]
    missing = [f"{r.home} v {r.away} ({r.kickoff_utc.isoformat()})"
               for r in due.itertuples() if (r.home, r.away) not in played]
    report["fixtures_due"] = int(len(due))
    report["due_without_result"] = missing
    if missing:
        raise GateError(f"results feed incomplete: {len(missing)} past fixtures have no result, e.g. {missing[:3]}")

    unknown = played - set(zip(fixtures.home, fixtures.away))
    if unknown:
        raise GateError(f"results not in fixture list: {sorted(unknown)[:3]}")

    merged = current.merge(openfootball_current, on=["home", "away"], suffixes=("", "_of"))
    disagreements = merged[(merged.FTHG != merged.FTHG_of) | (merged.FTAG != merged.FTAG_of)]
    report["cross_checked_results"] = int(len(merged))
    report["cross_check_disagreements"] = disagreements[["home", "away", "FTHG", "FTAG", "FTHG_of", "FTAG_of"]].to_dict("records")
    if len(disagreements):
        raise GateError(f"feeds disagree on {len(disagreements)} results")

    latest = (current.kickoff_utc.max() + MATCH_DURATION).to_pydatetime() if len(current) else None
    fresh = data_freshness(latest, now, max_age_hours=max_age_hours)
    report["freshness"] = {**fresh, "latest_result_available_at": latest.isoformat() if latest else None}
    if fresh["status"] != "fresh":
        raise GateError(f"results feed is {fresh['status']}: {fresh}")
    return report


def build_training(historical_dir: Path, current: pd.DataFrame, now: datetime) -> pd.DataFrame:
    frames = []
    for season in HISTORICAL_SEASONS:
        path = historical_dir / f"{season}.json"
        if not path.is_file():
            raise GateError(f"missing historical season file {path}")
        part = parse_openfootball_file(path, season)
        part["HomeTeam"] = part["HomeTeam"].map(canonical_team)
        part["AwayTeam"] = part["AwayTeam"].map(canonical_team)
        frames.append(part[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]])
    live = current[current.kickoff_utc + MATCH_DURATION <= now]
    frames.append(pd.DataFrame({
        "Date": [k.astimezone(LONDON).date().isoformat() for k in live.kickoff_utc],
        "HomeTeam": live.home.values, "AwayTeam": live.away.values,
        "FTHG": live.FTHG.values, "FTAG": live.FTAG.values,
    }))
    training = pd.concat(frames, ignore_index=True)
    training["Date"] = pd.to_datetime(training["Date"])
    training = _coerce_goals(training).sort_values("Date").reset_index(drop=True)
    return training


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--historical-dir", default=str(ROOT / "data/raw/openfootball"))
    parser.add_argument("--fixtures-json", default=str(ROOT / "data/raw/live/of_2026-27.json"))
    parser.add_argument("--results-csv", default=str(ROOT / "data/raw/live/fd_2627_E0.csv"))
    parser.add_argument("--ledger", default=str(ROOT / "results/prospective/ledger.sqlite"))
    parser.add_argument("--output-dir", default=str(ROOT / "results/prospective"))
    parser.add_argument("--now", default=None, help="ISO timestamp with offset (default: current UTC time)")
    parser.add_argument("--horizon-days", type=float, default=7.0)
    parser.add_argument("--grace-hours", type=float, default=36.0,
                        help="hours after full time before a missing result counts as stale")
    parser.add_argument("--max-age-hours", type=float, default=240.0,
                        help="Stage 12 freshness limit on the latest result (covers international breaks)")
    parser.add_argument("--xi", type=float, default=0.0018)
    parser.add_argument("--reg", type=float, default=1.0)
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise SystemExit("--now must include a timezone offset")
    now = now.astimezone(timezone.utc)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures = load_fixtures(Path(args.fixtures_json))
    current = load_results_csv(Path(args.results_csv))
    current = current[current.kickoff_utc < now].reset_index(drop=True)
    of_current = load_openfootball_results(Path(args.fixtures_json), "2026-27")
    run = {"run_at_utc": now.isoformat(), "model": "v2.4.1", "xi": args.xi, "reg": args.reg,
           "inputs": {"fixtures_json_sha256": sha256_file(args.fixtures_json),
                      "results_csv_sha256": sha256_file(args.results_csv)}}
    try:
        run["gates"] = run_gates(fixtures, current, of_current, now,
                                 grace_hours=args.grace_hours, max_age_hours=args.max_age_hours)
    except GateError as exc:
        run["status"] = "blocked"
        run["reason"] = str(exc)
        (output_dir / f"run_{now:%Y%m%dT%H%M%SZ}.json").write_text(json.dumps(run, indent=2, default=str) + "\n")
        print(json.dumps(run, indent=2, default=str))
        return 2

    model = load_model_module("v2.4.1")
    training = build_training(Path(args.historical_dir), current, now)
    data_hash = hashlib.sha256(training.to_csv(index=False).encode()).hexdigest()
    model_training = training.copy()
    for column in ("HomeTeam", "AwayTeam"):
        model_training[column] = model_training[column].map(model._team_name)
    as_of = pd.Timestamp(now.astimezone(LONDON).date())
    params = model.fit_model(model_training, xi=args.xi, reg=args.reg, verbose=False, as_of_date=as_of)
    try:
        import subprocess
        code_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
    except Exception:
        code_sha = None

    played = set(zip(current.home, current.away))
    window = fixtures[(fixtures.kickoff_utc > now) &
                      (fixtures.kickoff_utc <= now + timedelta(days=args.horizon_days))]
    window = window[[(h, a) not in played for h, a in zip(window.home, window.away)]]

    forecasts, added, kept = [], 0, 0
    with ProspectiveLedger(args.ledger) as ledger:
        for row in window.sort_values("kickoff_utc").itertuples():
            key = fixture_key(row.kickoff_utc, row.home, row.away)
            mh, ma = model._team_name(row.home), model._team_name(row.away)
            probs = model._predict_outcome_probs(params, mh, ma, allow_new_teams=True)
            p = [float(x) for x in probs[:3]]
            total = sum(p)
            p = [x / total for x in p]
            existing = ledger.get_prediction(key)
            if existing is None:
                ledger.record_prediction(
                    fixture_key=key, predicted_at=now, kickoff_at=row.kickoff_utc.to_pydatetime(),
                    p_home=p[0], p_draw=p[1], p_away=p[2], model_version=params["model_version"],
                    code_sha=code_sha, data_snapshot_hash=data_hash,
                    extra={"xi": args.xi, "reg": args.reg, "training_matches": int(len(training)),
                           "prior_only": mh not in params["attack"] or ma not in params["attack"]},
                )
                added += 1
            else:
                kept += 1
            forecasts.append({"fixture_key": key, "kickoff_utc": row.kickoff_utc.isoformat(),
                              "home": row.home, "away": row.away,
                              "p_home": round(p[0], 4), "p_draw": round(p[1], 4), "p_away": round(p[2], 4),
                              "prior_only": mh not in params["attack"] or ma not in params["attack"],
                              "status": "recorded" if existing is None else "already_in_ledger"})
        settled = 0
        for r in current.itertuples():
            key = fixture_key(r.kickoff_utc, r.home, r.away)
            if ledger.get_prediction(key) is not None:
                if ledger.record_outcome(key, int(r.FTHG), int(r.FTAG), now):
                    settled += 1
        run["ledger_fingerprint"] = ledger.fingerprint()

    run.update({"status": "ok", "training_matches": int(len(training)),
                "training_data_sha256": data_hash, "code_sha": code_sha,
                "forecasts_recorded": added, "forecasts_already_in_ledger": kept,
                "outcomes_settled": settled, "forecasts": forecasts})
    stamp = f"{now:%Y%m%dT%H%M%SZ}"
    (output_dir / f"run_{stamp}.json").write_text(json.dumps(run, indent=2, default=str) + "\n")
    if forecasts:
        pd.DataFrame(forecasts).to_csv(output_dir / f"forecasts_{stamp}.csv", index=False)
    print(json.dumps({k: v for k, v in run.items() if k != "forecasts"}, indent=2, default=str))
    for f in forecasts:
        print(f"{f['kickoff_utc'][:16]}  {f['home']:>26} v {f['away']:<26} "
              f"H {f['p_home']:.3f}  D {f['p_draw']:.3f}  A {f['p_away']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
