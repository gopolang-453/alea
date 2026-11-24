#!/usr/bin/env python3
"""Scheduled prospective forecasting: settle, gate, forecast, report.

Pipeline (fails closed; see docs/OPERATIONS.md for recovery):
 1. Verify the frozen champion (``config/model_registry.json`` module hash).
 2. Load the OpenFootball fixture list (CC0) and validate its structure.
 3. Load current-season results from a Wikipedia snapshot (CC BY-SA 4.0;
    ``--fetch-wikipedia`` downloads one) and, optionally, cross-check sources:
    OpenFootball scores in the fixture file and a *local* football-data.co.uk
    CSV (``--crosscheck-csv``; personal/academic fair use only, never committed).
 4. Structural gates: team names consistent across sources, every result maps
    to exactly one fixture, no unparseable score cells for due fixtures.
 5. Settle ledger forecasts whose results are available. Sources must agree;
    disagreements are logged as conflicts and nothing is overwritten.
 6. Data gates: completeness (isolated gaps are tolerated only when later
    results exist - the signature of a postponement), cross-source agreement,
    freshness. Any failure blocks forecasting (exit code 2).
 7. Fit the frozen champion on results available before ``--now`` and forecast
    fixtures with listed kickoff in ``(now + min_lead, now + horizon]``.
    Registered challengers are recorded for the same fixtures.
 8. Append to the ledger (never overwrite), write JSON + Markdown reports and a
    log file. Exit 0 ok, 2 blocked by a gate, 3 ledger integrity failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_openfootball import parse_openfootball_file  # noqa: E402
from scripts.run_stage9_mle_backtest import _coerce_goals, load_model_module  # noqa: E402
from stages.stage1.data_store import canonical_team, parse_match_dates  # noqa: E402
from stages.stage1.live_sources import (  # noqa: E402
    LONDON,
    SourceError,
    attach_kickoffs,
    fetch_wikipedia_snapshot,
    load_openfootball_fixtures,
    load_openfootball_results as _load_of_results,
    load_wikipedia_snapshot,
    london_to_utc,
    results_not_in_fixtures,
    validate_fixture_list,
)
from stages.stage12.reliability import data_freshness, sha256_file  # noqa: E402
from stages.stage9.candidates import EloConfig, OrderedLogit, pre_match_features  # noqa: E402
from stages.stage9.prospective_evaluation import dumps, evaluate_ledger, render_markdown  # noqa: E402
from stages.stage9.prospective_ledger import LedgerError, ProspectiveLedger, match_identity  # noqa: E402

HISTORICAL_SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
CURRENT_SEASON = "2026-27"
MATCH_DURATION = timedelta(hours=2)
ELO_BURN_IN = 380
ORDERED_LOGIT_RIDGE = 0.001
log = logging.getLogger("alea.prospective")


class GateError(RuntimeError):
    pass


# ----------------------------------------------------------- compatibility API
def fixture_key(kickoff_utc: datetime, home: str, away: str) -> str:
    return f"{kickoff_utc.astimezone(LONDON).date().isoformat()}|{home}|{away}"


def _london_to_utc(date_str: str, time_str: str | None) -> datetime:
    return london_to_utc(date_str, time_str)


def load_fixtures(path: Path) -> pd.DataFrame:
    try:
        return load_openfootball_fixtures(path)
    except SourceError as exc:
        raise GateError(str(exc)) from exc


def load_openfootball_results(path: Path, season: str = CURRENT_SEASON) -> pd.DataFrame:
    return _load_of_results(path)


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
            "kickoff_utc": london_to_utc(day.date().isoformat(), str(time_str)),
            "home": canonical_team(row["HomeTeam"]),
            "away": canonical_team(row["AwayTeam"]),
            "FTHG": int(row["FTHG"]),
            "FTAG": int(row["FTAG"]),
        })
    frame = pd.DataFrame(rows, columns=["kickoff_utc", "home", "away", "FTHG", "FTAG"])
    if frame.duplicated(["home", "away"]).any():
        raise GateError("results CSV repeats a home/away pairing")
    return frame


# ------------------------------------------------------------------- gates
def run_gates(fixtures, current, crosschecks, now, *, grace_hours, max_age_hours, min_later_results=5):
    """Completeness, consistency and freshness gates. Raises GateError.

    ``crosschecks`` is a DataFrame or ``{name: DataFrame}`` of other result
    feeds; every result present in both must agree exactly.

    A due fixture without a result is tolerated (reported as a suspected
    postponement) only if at least ``min_later_results`` results exist for
    fixtures listed three or more days later. Otherwise the feed is treated
    as stale and the run is blocked.
    """
    if isinstance(crosschecks, pd.DataFrame):
        crosschecks = {"openfootball": crosschecks}
    report = {}
    played = set(zip(current.home, current.away))
    due = fixtures[fixtures.kickoff_utc + MATCH_DURATION + timedelta(hours=grace_hours) < now]
    listed = dict(zip(zip(fixtures.home, fixtures.away), fixtures.kickoff_utc))
    result_kickoffs = [listed[p] for p in played if p in listed]
    suspected, missing = [], []
    for r in due.itertuples():
        if (r.home, r.away) in played:
            continue
        later = sum(1 for k in result_kickoffs if k >= r.kickoff_utc + timedelta(days=3))
        entry = f"{r.home} v {r.away} ({r.kickoff_utc.isoformat()})"
        (suspected if later >= min_later_results else missing).append(entry)
    report["fixtures_due"] = int(len(due))
    report["due_without_result"] = missing
    report["suspected_postponed"] = suspected
    if missing:
        raise GateError(f"results feed incomplete: {len(missing)} past fixtures have no result, e.g. {missing[:3]}")

    unknown = played - set(zip(fixtures.home, fixtures.away))
    if unknown:
        raise GateError(f"results not in fixture list: {sorted(unknown)[:3]}")

    report["cross_checks"] = {}
    total_disagreements = 0
    for name, other in crosschecks.items():
        merged = current.merge(other, on=["home", "away"], suffixes=("", "_x"))
        bad = merged[(merged.FTHG != merged.FTHG_x) | (merged.FTAG != merged.FTAG_x)]
        only_other = sorted(set(zip(other.home, other.away)) - played)
        report["cross_checks"][name] = {
            "compared": int(len(merged)),
            "disagreements": bad[["home", "away", "FTHG", "FTAG", "FTHG_x", "FTAG_x"]].to_dict("records"),
            "results_only_in_crosscheck": [f"{h} v {a}" for h, a in only_other],
        }
        total_disagreements += len(bad)
    # Backwards-compatible keys for the single-crosscheck case.
    first = next(iter(report["cross_checks"].values()), {"compared": 0, "disagreements": []})
    report["cross_checked_results"] = first["compared"]
    report["cross_check_disagreements"] = first["disagreements"]
    if total_disagreements:
        raise GateError(f"feeds disagree on {total_disagreements} results")

    latest = (max(result_kickoffs) + MATCH_DURATION).to_pydatetime() if result_kickoffs else None
    if latest is None and len(current):
        latest = (current.kickoff_utc.max() + MATCH_DURATION).to_pydatetime()
    if latest is not None and latest > now:
        # A result whose listed date is still ahead was played early; it is
        # evidence the feed is current, not a future timestamp.
        latest = now
    fresh = data_freshness(latest, now, max_age_hours=max_age_hours)
    report["freshness"] = {**fresh, "latest_result_available_at": latest.isoformat() if latest else None}
    if fresh["status"] != "fresh":
        raise GateError(f"results feed is {fresh['status']}: {fresh}")
    return report


# ----------------------------------------------------------------- training
def build_training(historical_dir: Path, current: pd.DataFrame, now: datetime, *,
                   require_past_kickoff: bool = True) -> pd.DataFrame:
    """Historical seasons + current results known at ``now``.

    Current-season dates are listed (OpenFootball) dates, clamped to the run
    date so a match played earlier than listed never gets a future date.
    """
    frames = []
    for season in HISTORICAL_SEASONS:
        path = historical_dir / f"{season}.json"
        if not path.is_file():
            raise GateError(f"missing historical season file {path}")
        part = parse_openfootball_file(path, season)
        part["HomeTeam"] = part["HomeTeam"].map(canonical_team)
        part["AwayTeam"] = part["AwayTeam"].map(canonical_team)
        frames.append(part[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]])
    # The frozen champion excludes same-day matches from training (its own
    # leakage guard), so a result that is already known on the run date (an
    # evening run, or a match played earlier than listed) is dated the day
    # before the run. That shifts its time-decay weight by at most one day.
    latest_allowed = now.astimezone(LONDON).date() - timedelta(days=1)
    # A result that is present in the snapshot has been played even if its
    # listed date is later (date moved earlier), so the primary feed passes
    # require_past_kickoff=False; the timestamp-based filter is kept for
    # feeds that may contain scheduled rows.
    live = current[current.kickoff_utc + MATCH_DURATION <= now] if require_past_kickoff else current
    frames.append(pd.DataFrame({
        "Date": [min(k.astimezone(LONDON).date(), latest_allowed).isoformat() for k in live.kickoff_utc],
        "HomeTeam": live.home.values, "AwayTeam": live.away.values,
        "FTHG": live.FTHG.values, "FTAG": live.FTAG.values,
    }))
    training = pd.concat(frames, ignore_index=True)
    training["Date"] = pd.to_datetime(training["Date"])
    return _coerce_goals(training).sort_values("Date", kind="stable").reset_index(drop=True)


def challenger_probabilities(training: pd.DataFrame, window: pd.DataFrame, now: datetime,
                             champion_p: np.ndarray) -> dict:
    """Registered Stage 9 challengers for the forecast window (protocol-identical)."""
    results = training.copy()
    results["available_at"] = (results["Date"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
    results["actual"] = np.where(results.FTHG > results.FTAG, "H",
                                 np.where(results.FTHG == results.FTAG, "D", "A"))
    pool = results.copy()
    pool["cutoff_utc"] = pool["Date"].dt.tz_localize("UTC")
    pool[["elo_diff", "form_diff"]] = pre_match_features(results, pool, elo=EloConfig()).values
    pool = pool.iloc[ELO_BURN_IN:]
    queries = pd.DataFrame({"HomeTeam": window.home.values, "AwayTeam": window.away.values,
                            "cutoff_utc": [now] * len(window)})
    feats = pre_match_features(results, queries, elo=EloConfig())
    elo_p = OrderedLogit(ORDERED_LOGIT_RIDGE).fit(pool.elo_diff.to_numpy(), pool.actual.to_numpy()) \
        .predict(feats.elo_diff.to_numpy())
    return {"elo_ordered_logit": elo_p, "dc_elo_equal_average": (champion_p + elo_p) / 2.0,
            "_elo_diff": feats.elo_diff.to_numpy()}


# --------------------------------------------------------------------- main
def _code_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def verify_champion(registry: dict) -> None:
    champ = registry["champion"]
    actual = sha256_file(ROOT / champ["module"])
    if actual != champ["module_sha256"]:
        raise GateError(f"frozen champion {champ['module']} hash {actual} does not match registry "
                        f"{champ['module_sha256']}; refusing to forecast")


def _write_outputs(output_dir: Path, stamp: str, run: dict, ledger: ProspectiveLedger | None,
                   registry: dict, now: datetime, grace_hours: float) -> None:
    (output_dir / "runs").mkdir(parents=True, exist_ok=True)
    (output_dir / "runs" / f"run_{stamp}.json").write_text(json.dumps(run, indent=2, default=str) + "\n")
    if run.get("forecasts"):
        pd.DataFrame(run["forecasts"]).to_csv(output_dir / "runs" / f"forecasts_{stamp}.csv", index=False)
    if ledger is not None:
        ev = evaluate_ledger(ledger, registry, now, grace_hours=grace_hours)
        (output_dir / "evaluation.json").write_text(dumps(ev))
        report = render_markdown(ev, run=run)
        (output_dir / "report.md").write_text(report)
        (output_dir / "runs" / f"report_{stamp}.md").write_text(report)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--historical-dir", default=str(ROOT / "data/raw/openfootball"))
    parser.add_argument("--fixtures-json", default=str(ROOT / "data/raw/live/of_2026-27.json"))
    parser.add_argument("--wikipedia-snapshot", default=str(ROOT / "data/raw/live/wikipedia_2026-27.json"))
    parser.add_argument("--fetch-wikipedia", action="store_true",
                        help="download the latest revision to --wikipedia-snapshot first")
    parser.add_argument("--crosscheck-csv", default=None,
                        help="optional local football-data.co.uk CSV (never committed)")
    parser.add_argument("--registry", default=str(ROOT / "config/model_registry.json"))
    parser.add_argument("--ledger", default=str(ROOT / "results/prospective/ledger.sqlite"))
    parser.add_argument("--init-ledger", action="store_true", help="allow creating a new empty ledger")
    parser.add_argument("--output-dir", default=str(ROOT / "results/prospective"))
    parser.add_argument("--now", default=None, help="ISO timestamp with offset (default: current UTC time)")
    parser.add_argument("--horizon-days", type=float, default=7.0)
    parser.add_argument("--min-lead-hours", type=float, default=48.0,
                        help="only forecast fixtures listed at least this far ahead (covers TV date moves)")
    parser.add_argument("--grace-hours", type=float, default=60.0,
                        help="hours after listed full time before a missing result counts as overdue")
    parser.add_argument("--max-age-hours", type=float, default=240.0)
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise SystemExit("--now must include a timezone offset")
    now = now.astimezone(timezone.utc)
    stamp = f"{now:%Y%m%dT%H%M%SZ}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(output_dir / "logs" / f"run_{stamp}.log")
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    run = {"run_id": stamp, "run_at_utc": now.isoformat(), "status": "started",
           "champion": registry["champion"]["model_version"], "code_sha": _code_sha(),
           "parameters": {k: getattr(args, k) for k in ("horizon_days", "min_lead_hours", "grace_hours",
                                                          "max_age_hours")}}
    try:
        ledger = ProspectiveLedger(args.ledger, create=args.init_ledger)
    except LedgerError as exc:
        run.update(status="failed", reason=f"ledger unavailable: {exc}")
        log.error(run["reason"])
        _write_outputs(output_dir, stamp, run, None, registry, now, args.grace_hours)
        return 3
    with ledger:
        integrity = ledger.integrity_report()
        run["ledger_before"] = {k: integrity[k] for k in ("ok", "champion_forecasts", "outcomes", "fingerprint")}
        if not integrity["ok"]:
            run.update(status="failed", reason=f"ledger integrity failure: {integrity['problems']}")
            log.error(run["reason"])
            _write_outputs(output_dir, stamp, run, None, registry, now, args.grace_hours)
            return 3
        try:
            code = _pipeline(args, now, stamp, registry, ledger, run)
        except (GateError, SourceError) as exc:
            run.update(status="blocked", reason=str(exc))
            ledger.log_issue("error", "run_blocked", str(exc), run_id=stamp, at=now)
            log.error("BLOCKED: %s", exc)
            code = 2
        except Exception as exc:  # never fail silently: record, report, non-zero exit
            run.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
            ledger.log_issue("error", "run_failed", run["reason"], run_id=stamp, at=now)
            log.exception("FAILED")
            code = 1
        run["ledger_after"] = {"fingerprint": ledger.fingerprint(),
                               "challenger_fingerprint": ledger.challenger_fingerprint()}
        ledger.record_run(stamp, now, run["status"], {k: v for k, v in run.items() if k != "forecasts"})
        _write_outputs(output_dir, stamp, run, ledger, registry, now, args.grace_hours)
    log.info("status=%s recorded=%s settled=%s", run["status"], run.get("forecasts_recorded"),
             run.get("outcomes_settled"))
    print(json.dumps({k: v for k, v in run.items() if k not in ("forecasts", "gates")}, indent=2, default=str))
    return code


def _pipeline(args, now, stamp, registry, ledger: ProspectiveLedger, run: dict) -> int:
    verify_champion(registry)
    if args.fetch_wikipedia:
        snap = fetch_wikipedia_snapshot(CURRENT_SEASON)
        Path(args.wikipedia_snapshot).parent.mkdir(parents=True, exist_ok=True)
        Path(args.wikipedia_snapshot).write_text(json.dumps(snap), encoding="utf-8")
        log.info("fetched Wikipedia revision %s (%s)", snap["revid"], snap["timestamp"])
    fixtures = load_fixtures(Path(args.fixtures_json))
    problems = validate_fixture_list(fixtures)
    if problems:
        raise GateError(f"fixture list failed validation: {problems[:5]}")
    wiki = load_wikipedia_snapshot(args.wikipedia_snapshot)
    run["sources"] = {
        "fixtures": {"name": "OpenFootball football.json (CC0)", "sha256": sha256_file(args.fixtures_json)},
        "results": {"name": "Wikipedia (CC BY-SA 4.0)", "title": wiki.title, "revid": wiki.revid,
                    "revision_timestamp": wiki.revision_timestamp, "update_parameter": wiki.update_date,
                    "content_sha256": wiki.content_sha256, "results": int(len(wiki.results))},
        "wikipedia_attribution": wiki.attribution,
    }
    if wiki.revision_timestamp:
        rev_time = datetime.fromisoformat(wiki.revision_timestamp.replace("Z", "+00:00"))
        if rev_time > now + timedelta(minutes=5):
            raise GateError(f"Wikipedia revision {wiki.revid} is newer than the run time; "
                            "a backdated run would use future information")
    fixture_teams = set(fixtures.home) | set(fixtures.away)
    wiki_teams = set(wiki.teams.values())
    if wiki_teams != fixture_teams:
        raise GateError(f"team names inconsistent between sources: only Wikipedia {sorted(wiki_teams - fixture_teams)}, "
                        f"only fixtures {sorted(fixture_teams - wiki_teams)}")
    stray = results_not_in_fixtures(wiki.results, fixtures)
    if stray:
        raise GateError(f"Wikipedia results not in fixture list: {stray[:3]}")
    current = attach_kickoffs(wiki.results, fixtures)

    crosschecks = {"openfootball": load_openfootball_results(Path(args.fixtures_json))}
    if args.crosscheck_csv:
        crosschecks["football-data.co.uk (local)"] = load_results_csv(Path(args.crosscheck_csv))
        run["sources"]["crosscheck_csv_sha256"] = sha256_file(args.crosscheck_csv)
    for name, frame in crosschecks.items():
        bad_teams = (set(frame.home) | set(frame.away)) - fixture_teams
        if bad_teams:
            raise GateError(f"{name}: unknown team names {sorted(bad_teams)}")

    # ---- settlement (before data gates: agreeing results can always be settled)
    by_pair = {name: {(r.home, r.away): (int(r.FTHG), int(r.FTAG)) for r in frame.itertuples()}
               for name, frame in [("wikipedia", current), *crosschecks.items()]}
    unparsed = {(u["home"], u["away"]): u["cell"] for u in wiki.unparsed}
    settled, conflicts = [], []
    for pred in ledger.predictions():
        season, home, away = match_identity(pred["fixture_key"])
        if season != CURRENT_SEASON:
            continue
        obs = [(src, *pairs[(home, away)], str(wiki.revid) if src == "wikipedia" else None)
               for src, pairs in by_pair.items() if (home, away) in pairs]
        if (home, away) in unparsed:
            ledger.log_issue("warning", "unparsed_result_cell", unparsed[(home, away)],
                             fixture_key=pred["fixture_key"], run_id=stamp, at=now)
        if not obs:
            continue
        if not any(o[0] == "wikipedia" for o in obs):
            ledger.log_issue("warning", "result_missing_from_primary",
                             f"result only in {[o[0] for o in obs]}", fixture_key=pred["fixture_key"],
                             run_id=stamp, at=now)
            continue
        status = ledger.observe_and_settle(pred["fixture_key"], obs, now, run_id=stamp)
        if status == "settled":
            settled.append(pred["fixture_key"])
        elif status == "conflict":
            conflicts.append(pred["fixture_key"])
        listed_ko = datetime.fromisoformat(pred["kickoff_at"])
        if now < listed_ko - timedelta(hours=24):
            ledger.log_issue("warning", "played_well_before_listed_kickoff",
                             f"result observed {now.isoformat()} but listed kickoff {pred['kickoff_at']}; "
                             "verify the forecast preceded the actual kickoff", fixture_key=pred["fixture_key"],
                             run_id=stamp, at=now)
    run["outcomes_settled"] = settled
    run["settlement_conflicts"] = conflicts
    for key, cell in unparsed.items():
        ledger.log_issue("warning", "unparsed_result_cell", f"{key[0]} v {key[1]}: {cell}", run_id=stamp, at=now)

    # ---- data gates
    run["gates"] = run_gates(fixtures, current, crosschecks, now,
                             grace_hours=args.grace_hours, max_age_hours=args.max_age_hours)
    for entry in run["gates"]["suspected_postponed"]:
        ledger.log_issue("warning", "suspected_postponement", entry, run_id=stamp, at=now)
    due_unparsed = [k for k in unparsed if k in set(zip(fixtures.home, fixtures.away))]
    if due_unparsed:
        raise GateError(f"unparseable result cells: {due_unparsed[:3]}")

    # ---- fit frozen champion
    model = load_model_module("v2.4.1")
    training = build_training(Path(args.historical_dir), current, now, require_past_kickoff=False)
    data_hash = hashlib.sha256(training.to_csv(index=False).encode()).hexdigest()
    params_cfg = registry["champion"]["parameters"]
    model_training = training.copy()
    for column in ("HomeTeam", "AwayTeam"):
        model_training[column] = model_training[column].map(model._team_name)
    as_of = pd.Timestamp(now.astimezone(LONDON).date())
    params = model.fit_model(model_training, xi=params_cfg["xi"], reg=params_cfg["reg"],
                             verbose=False, as_of_date=as_of)
    if params["model_version"] != registry["champion"]["model_version"]:
        raise GateError(f"fitted model reports {params['model_version']}, registry says "
                        f"{registry['champion']['model_version']}")
    log.info("champion fitted on %d matches (sha256 %s)", len(training), data_hash[:12])

    played = set(zip(current.home, current.away))
    lead = now + timedelta(hours=args.min_lead_hours)
    in_horizon = fixtures[(fixtures.kickoff_utc > now) &
                          (fixtures.kickoff_utc <= now + timedelta(days=args.horizon_days))]
    in_horizon = in_horizon[[(h, a) not in played for h, a in zip(in_horizon.home, in_horizon.away)]]
    run["too_close_to_kickoff"] = [fixture_key(r.kickoff_utc, r.home, r.away)
                                   for r in in_horizon.itertuples() if r.kickoff_utc <= lead]
    window = in_horizon[in_horizon.kickoff_utc > lead].sort_values("kickoff_utc").reset_index(drop=True)

    champ_p = np.zeros((len(window), 3))
    prior_only, existing_rows = [], []
    for i, row in enumerate(window.itertuples()):
        key = fixture_key(row.kickoff_utc, row.home, row.away)
        existing = ledger.get_prediction(key) or ledger.find_prediction_for_match(key)
        existing_rows.append(existing)
        mh, ma = model._team_name(row.home), model._team_name(row.away)
        prior_only.append(mh not in params["attack"] or ma not in params["attack"])
        if existing is not None:
            # The recorded forecast is the champion forecast; it is never recomputed.
            champ_p[i] = [existing["p_home"], existing["p_draw"], existing["p_away"]]
        else:
            probs = np.asarray(model._predict_outcome_probs(params, mh, ma, allow_new_teams=True)[:3], dtype=float)
            champ_p[i] = probs / probs.sum()
    challengers = challenger_probabilities(training, window, now, champ_p) if len(window) else {}
    registered = {c["model_id"]: c for c in registry.get("challengers", [])}

    forecasts, added, kept, added_ch = [], 0, 0, 0
    common = {"xi": params_cfg["xi"], "reg": params_cfg["reg"], "training_matches": int(len(training))}
    provenance = {"results_source": "wikipedia", "wikipedia_revid": wiki.revid,
                  "fixtures_sha256": run["sources"]["fixtures"]["sha256"], "run_id": stamp}
    for i, row in enumerate(window.itertuples()):
        key = fixture_key(row.kickoff_utc, row.home, row.away)
        p = [float(x) for x in champ_p[i]]
        existing = existing_rows[i]
        if existing is None:
            ledger.record_prediction(
                fixture_key=key, predicted_at=now, kickoff_at=row.kickoff_utc.to_pydatetime(),
                p_home=p[0], p_draw=p[1], p_away=p[2], model_version=params["model_version"],
                code_sha=run["code_sha"], data_snapshot_hash=data_hash,
                extra={**common, "prior_only": prior_only[i], **provenance})
            added += 1
            status = "recorded"
        else:
            kept += 1
            status = "already_in_ledger" if existing["fixture_key"] == key else \
                f"already_forecast_as {existing['fixture_key']}"
        ledger_key = key if existing is None else existing["fixture_key"]
        have = {c["model_id"] for c in ledger.challenger_predictions() if c["fixture_key"] == ledger_key}
        kickoff = datetime.fromisoformat(existing["kickoff_at"]) if existing else row.kickoff_utc.to_pydatetime()
        for model_id, values in challengers.items():
            if model_id not in registered or model_id in have or now >= kickoff:
                continue
            q = [float(x) for x in values[i]]
            q = [x / sum(q) for x in q]
            ledger.record_challenger_prediction(
                model_id=model_id, fixture_key=ledger_key, predicted_at=now, kickoff_at=kickoff,
                p_home=q[0], p_draw=q[1], p_away=q[2], model_version=registered[model_id]["model_version"],
                code_sha=run["code_sha"], data_snapshot_hash=data_hash,
                extra={"elo_diff": float(challengers["_elo_diff"][i]), **provenance})
            added_ch += 1
        forecasts.append({"fixture_key": key, "kickoff_utc": row.kickoff_utc.isoformat(),
                          "home": row.home, "away": row.away, "p_home": round(p[0], 4),
                          "p_draw": round(p[1], 4), "p_away": round(p[2], 4),
                          "prior_only": prior_only[i], "status": status})
    run.update({"status": "ok", "training_matches": int(len(training)), "training_data_sha256": data_hash,
                "forecasts_recorded": added, "forecasts_already_in_ledger": kept,
                "challenger_forecasts_recorded": added_ch, "forecasts": forecasts})
    for f in forecasts:
        log.info("%s %s v %s H %.3f D %.3f A %.3f [%s]", f["kickoff_utc"][:16], f["home"], f["away"],
                 f["p_home"], f["p_draw"], f["p_away"], f["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
