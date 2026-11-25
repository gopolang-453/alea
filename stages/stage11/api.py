"""Stage 11 prediction API: read-only HTTP service over the prospective ledger.

The service never fits or switches models. It serves the forecasts that the
scheduled pipeline froze in the append-only ledger, and it refuses to serve
(HTTP 503) when the ledger contains a model version other than the registered
champion, when the frozen champion file does not match its registered hash,
or when the ledger fails its integrity check.

Endpoints (all GET, JSON unless noted)
  /health                              liveness + readiness (200 ok/degraded, 503 unhealthy)
  /v1/status                           model, ledger fingerprint, counts, data freshness
  /v1/predictions/upcoming             ?days=1..60 &include_challengers=true|false
  /v1/predictions/history              ?team= &from=YYYY-MM-DD &to=YYYY-MM-DD &status= &limit=1..500 &offset=
  /v1/predictions/<fixture_key>        URL-encoded "YYYY-MM-DD|home|away"
  /v1/evaluation                       settled-forecast metrics and challenger comparison
  /v1/fixtures/upcoming                ?days=1..60  listed fixtures (OpenFootball) + forecast status
  /metrics                             Prometheus text format
  /  and static files                  the mobile web app (web/), from a fixed allowlist
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote

from stages.stage12.reliability import sha256_file
from stages.stage9.prospective_evaluation import evaluate_ledger
from stages.stage9.prospective_ledger import LedgerError, ProspectiveLedger, split_fixture_key

log = logging.getLogger("alea.api")
API_VERSION = "1.0"
_STATUSES = {"settled", "void", "conflict", "pending", "overdue", "postponed", "abandoned"}
_TEAM = re.compile(r"^[a-z0-9 .'&-]{2,60}$")
# Shown on every data response: result observations are derived from Wikipedia
# (CC BY-SA 4.0, attribution + share-alike), fixtures from OpenFootball (CC0).
DATA_ATTRIBUTION = {
    "forecasts": "ALEA model output (alea-dc-v2.4.1 champion; registered challengers)",
    "results": ("Wikipedia contributors, '2026\u201327 Premier League', CC BY-SA 4.0 "
                "(https://creativecommons.org/licenses/by-sa/4.0/); per-run revision ids in /v1/status"),
    "fixtures": "OpenFootball football.json, CC0 1.0 (https://github.com/openfootball/football.json)",
    "licensing_notes": "See docs/DATA_SOURCES_AND_LICENSING.md. Not legal advice; commercial use needs review.",
}


FIXTURES_FILE = "fixtures_upcoming.json"
MIN_LEAD_HOURS = 48          # the pipeline only forecasts fixtures listed >= 48 h ahead
# Same-origin only, no inline script, no framing. Applied to every response.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = [("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", CSP),
                    ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()"),
                    ("Cross-Origin-Opener-Policy", "same-origin")]
_STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".json": "application/json",
                 ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}


def _load_static(web_dir: Optional[Path]) -> Dict[str, Tuple[bytes, str]]:
    """Read the web app into memory once. Only regular files under ``web_dir``
    with a known type are served, looked up by exact URL path, so request
    paths can never reach anything else on disk."""
    files: Dict[str, Tuple[bytes, str]] = {}
    if web_dir is None or not web_dir.is_dir():
        return files
    base = web_dir.resolve()
    for f in sorted(base.rglob("*")):
        if not f.is_file() or f.is_symlink() or f.suffix not in _STATIC_TYPES:
            continue
        resolved = f.resolve()
        if base not in resolved.parents:
            continue
        rel = resolved.relative_to(base).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        files["/" + rel] = (resolved.read_bytes(), _STATIC_TYPES[f.suffix])
    if "/index.html" in files:
        files["/"] = files["/index.html"]
    return files


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
            500: "Internal Server Error", 503: "Service Unavailable"}


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Dict[Tuple[str, int], int] = {}
        self.latency_sum = 0.0
        self.latency_count = 0
        self.started = time.time()

    def observe(self, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(route, status)] = self.requests.get((route, status), 0) + 1
            self.latency_sum += seconds
            self.latency_count += 1

    def render(self, gauges: Dict[str, float]) -> str:
        lines = ["# HELP alea_http_requests_total HTTP requests by route and status.",
                 "# TYPE alea_http_requests_total counter"]
        with self._lock:
            for (route, status), n in sorted(self.requests.items()):
                lines.append(f'alea_http_requests_total{{route="{route}",status="{status}"}} {n}')
            lines += ["# TYPE alea_http_request_seconds_sum counter",
                      f"alea_http_request_seconds_sum {self.latency_sum:.6f}",
                      "# TYPE alea_http_request_seconds_count counter",
                      f"alea_http_request_seconds_count {self.latency_count}"]
        lines.append(f"alea_uptime_seconds {time.time() - self.started:.0f}")
        for name, value in sorted(gauges.items()):
            lines += [f"# TYPE {name} gauge", f"{name} {value}"]
        return "\n".join(lines) + "\n"


def _parse_day(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "invalid_parameter", f"{name} must be YYYY-MM-DD")


def _int(params: Dict[str, List[str]], name: str, default: int, lo: int, hi: int) -> int:
    raw = params.get(name, [str(default)])[-1]
    if not re.fullmatch(r"\d{1,6}", raw):
        raise ApiError(400, "invalid_parameter", f"{name} must be an integer between {lo} and {hi}")
    value = int(raw)
    if not lo <= value <= hi:
        raise ApiError(400, "invalid_parameter", f"{name} must be between {lo} and {hi}")
    return value


def _bool(params: Dict[str, List[str]], name: str) -> bool:
    raw = params.get(name, ["false"])[-1].lower()
    if raw not in ("true", "false", "1", "0"):
        raise ApiError(400, "invalid_parameter", f"{name} must be true or false")
    return raw in ("true", "1")


class ForecastAPI:
    """WSGI application. ``clock`` is injectable for tests."""

    def __init__(self, ledger_path: str | Path, registry_path: str | Path, *, root: str | Path,
                 max_staleness_hours: float = 216.0, web_dir: str | Path | None = "default",
                 fixtures_path: str | Path | None = None, sync_status: Optional[Callable[[], Dict[str, Any]]] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.ledger_path = Path(ledger_path)
        self.registry_path = Path(registry_path)
        self.root = Path(root)
        self.max_staleness_hours = max_staleness_hours
        self.clock = clock
        self.metrics = Metrics()
        if web_dir == "default":
            web_dir = self.root / "web"
        self.static = _load_static(Path(web_dir) if web_dir else None)
        self.fixtures_path = Path(fixtures_path) if fixtures_path else self.ledger_path.parent / FIXTURES_FILE
        self.sync_status = sync_status

    # ------------------------------------------------------------- helpers
    def _registry(self) -> Dict[str, Any]:
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("model registry unreadable: %s", exc)  # details (paths) stay in the server log
            raise ApiError(503, "registry_unavailable", "model registry unreadable")

    def _open(self) -> ProspectiveLedger:
        try:
            return ProspectiveLedger(self.ledger_path, read_only=True)
        except LedgerError as exc:
            log.error("ledger unavailable: %s", exc)
            missing = "not found" in str(exc)
            raise ApiError(503, "ledger_unavailable",
                           "ledger database not found" if missing else "ledger database unreadable or corrupt")

    def _checks(self, ledger: ProspectiveLedger, registry: Dict[str, Any]) -> Dict[str, Any]:
        problems, warnings = [], []
        champ = registry["champion"]
        try:
            if sha256_file(self.root / champ["module"]) != champ["module_sha256"]:
                problems.append("frozen champion file does not match registered hash")
        except Exception as exc:  # missing file etc.
            log.error("cannot verify champion file: %s", exc)
            problems.append("cannot verify frozen champion file")
        integrity = ledger.integrity_report()
        if not integrity["ok"]:
            problems.extend(integrity["problems"])
        versions = sorted({p["model_version"] for p in ledger.predictions()})
        foreign = [v for v in versions if v != champ["model_version"]]
        if foreign:
            problems.append(f"ledger contains non-champion model versions {foreign}; refusing to serve")
        runs = ledger.runs()
        ok_runs = [r for r in runs if r["status"] == "ok"]
        now = self.clock()
        freshness: Dict[str, Any] = {"last_run_at": runs[-1]["started_at"] if runs else None,
                                     "last_run_status": runs[-1]["status"] if runs else None,
                                     "last_successful_run_at": ok_runs[-1]["started_at"] if ok_runs else None}
        if ok_runs:
            age = (now - datetime.fromisoformat(ok_runs[-1]["started_at"])).total_seconds() / 3600
            freshness["age_hours"] = round(age, 2)
            if age > self.max_staleness_hours:
                warnings.append(f"last successful forecast run is {age:.0f} h old "
                                f"(limit {self.max_staleness_hours:.0f} h)")
            summary = json.loads(ok_runs[-1]["summary_json"])
            freshness["results_source"] = summary.get("sources", {}).get("results")
        else:
            freshness["age_hours"] = None
            warnings.append("no successful forecast run recorded in the ledger")
        if runs and runs[-1]["status"] != "ok":
            warnings.append(f"latest run status is {runs[-1]['status']}")
        status = "unhealthy" if problems else ("degraded" if warnings else "ok")
        return {"status": status, "problems": problems, "warnings": warnings, "freshness": freshness,
                "integrity": {k: integrity[k] for k in ("ok", "sqlite_integrity_check", "champion_forecasts",
                                                        "challenger_forecasts", "outcomes", "fingerprint")}}

    def _serving_ledger(self):
        registry = self._registry()
        ledger = self._open()
        checks = self._checks(ledger, registry)
        if checks["status"] == "unhealthy":
            ledger.close()
            raise ApiError(503, "not_serving", "; ".join(checks["problems"]))
        return ledger, registry, checks

    @staticmethod
    def _forecast(p: Dict[str, Any], status=None) -> Dict[str, Any]:
        day, home, away = split_fixture_key(p["fixture_key"])
        probs = {"home": p["p_home"], "draw": p["p_draw"], "away": p["p_away"]}
        total = sum(probs.values())
        if abs(total - 1.0) > 1e-6:
            raise ApiError(500, "invalid_probabilities", f"{p['fixture_key']} probabilities sum to {total}")
        extra = json.loads(p["payload_json"]).get("extra", {})
        xg = None
        if p.get("expected_goals_home") is not None and p.get("expected_goals_away") is not None:
            xg = {"home": p["expected_goals_home"], "away": p["expected_goals_away"]}
        scores = extra.get("top_scorelines")
        out = {"fixture_key": p["fixture_key"], "date": day.isoformat(), "home": home, "away": away,
               "kickoff_at_listed": p["kickoff_at"], "predicted_at": p["predicted_at"],
               "model_version": p["model_version"], "probabilities": probs,
               "training_data_sha256": p["data_snapshot_hash"], "code_sha": p.get("code_sha"),
               "training_matches": extra.get("training_matches"),
               "results_source_revision": extra.get("wikipedia_revid"),
               "prior_only": extra.get("prior_only"),
               # Model expected goals (Dixon-Coles lambda/mu) and most likely exact scores. Recorded at
               # forecast time for forecasts made from release 1.0 on; null for earlier rows, which
               # are never recomputed.
               "expected_goals": xg,
               "top_scorelines": scores if isinstance(scores, list) else None}
        if status is not None:
            out["status"] = status.status
            if status.outcome:
                out["result"] = {"home_goals": status.home_goals, "away_goals": status.away_goals,
                                 "outcome": status.outcome}
            if status.reason:
                out["status_reason"] = status.reason
        return out

    # ------------------------------------------------------------- routes
    def health(self, params):
        registry = self._registry()
        try:
            ledger = self._open()
        except ApiError as exc:
            return 503, {"status": "unhealthy", "problems": [exc.message], "api_version": API_VERSION}
        with ledger:
            checks = self._checks(ledger, registry)
        checks.update(api_version=API_VERSION, champion=registry["champion"]["model_version"],
                      time=self.clock().isoformat())
        if self.sync_status is not None:
            sync = self.sync_status()
            checks["ledger_sync"] = {k: sync.get(k) for k in ("last_attempt_at", "last_success_at",
                                                              "last_change_at", "last_error")}
            if sync.get("last_error") and checks["status"] == "ok":
                checks["status"] = "degraded"
                checks["warnings"].append(sync["last_error"])
        return (503 if checks["status"] == "unhealthy" else 200), checks

    def status(self, params):
        ledger, registry, checks = self._serving_ledger()
        with ledger:
            return 200, {"api_version": API_VERSION, "champion": registry["champion"],
                         "attribution": DATA_ATTRIBUTION,
                         "challengers": [c["model_id"] for c in registry.get("challengers", [])],
                         "health": checks["status"], "warnings": checks["warnings"],
                         "data_freshness": checks["freshness"], "ledger": checks["integrity"],
                         "recent_runs": [{k: r[k] for k in ("run_id", "started_at", "status")}
                                         for r in ledger.runs()[-10:]]}

    def upcoming(self, params):
        days = _int(params, "days", 7, 1, 60)
        with_ch = _bool(params, "include_challengers")
        ledger, registry, checks = self._serving_ledger()
        now = self.clock()
        with ledger:
            rows = [p for p in ledger.predictions()
                    if now < datetime.fromisoformat(p["kickoff_at"]) <= now + timedelta(days=days)]
            items = [self._forecast(p) for p in rows]
            if with_ch:
                by_key: Dict[str, list] = {}
                for c in ledger.challenger_predictions():
                    by_key.setdefault(c["fixture_key"], []).append(
                        {"model_id": c["model_id"], "model_version": c["model_version"],
                         "predicted_at": c["predicted_at"],
                         "probabilities": {"home": c["p_home"], "draw": c["p_draw"], "away": c["p_away"]}})
                for item in items:
                    item["challengers"] = by_key.get(item["fixture_key"], [])
        return 200, {"generated_at": now.isoformat(), "champion": registry["champion"]["model_version"],
                     "window_days": days, "count": len(items), "data_freshness": checks["freshness"],
                     "warnings": checks["warnings"], "predictions": items, "attribution": DATA_ATTRIBUTION,
                     "note": "Kickoff times are listed (OpenFootball) times and may differ from the actual kickoff."}

    def history(self, params):
        team = params.get("team", [None])[-1]
        if team is not None:
            team = team.strip().lower()
            if not _TEAM.fullmatch(team):
                raise ApiError(400, "invalid_parameter", "team must be 2-60 characters of letters, digits, spaces")
        start = _parse_day(params["from"][-1], "from") if "from" in params else None
        end = _parse_day(params["to"][-1], "to") if "to" in params else None
        if start and end and start > end:
            raise ApiError(400, "invalid_parameter", "from must not be after to")
        status = params.get("status", [None])[-1]
        if status is not None and status not in _STATUSES:
            raise ApiError(400, "invalid_parameter", f"status must be one of {sorted(_STATUSES)}")
        limit = _int(params, "limit", 100, 1, 500)
        offset = _int(params, "offset", 0, 0, 100000)
        ledger, registry, checks = self._serving_ledger()
        now = self.clock()
        with ledger:
            items = []
            for p in ledger.predictions():
                day, home, away = split_fixture_key(p["fixture_key"])
                if team and team not in (home, away):
                    continue
                if (start and day < start) or (end and day > end):
                    continue
                st = ledger.fixture_status(p["fixture_key"], now)
                if status and st.status != status:
                    continue
                items.append(self._forecast(p, st))
        return 200, {"total": len(items), "limit": limit, "offset": offset,
                     "predictions": items[offset:offset + limit], "attribution": DATA_ATTRIBUTION}

    def one(self, key: str):
        try:
            split_fixture_key(key)
        except LedgerError:
            raise ApiError(400, "invalid_fixture_key", "fixture key must be YYYY-MM-DD|home|away (URL-encoded)")
        ledger, registry, checks = self._serving_ledger()
        with ledger:
            p = ledger.get_prediction(key)
            if p is None:
                raise ApiError(404, "not_found", f"no forecast for {key}")
            item = self._forecast(p, ledger.fixture_status(key, self.clock()))
            item["challengers"] = [{"model_id": c["model_id"], "model_version": c["model_version"],
                                    "predicted_at": c["predicted_at"],
                                    "probabilities": {"home": c["p_home"], "draw": c["p_draw"], "away": c["p_away"]}}
                                   for c in ledger.challenger_predictions() if c["fixture_key"] == key]
            item["events"] = ledger.events(key)
            item["attribution"] = DATA_ATTRIBUTION
        return 200, item

    def evaluation(self, params):
        ledger, registry, checks = self._serving_ledger()
        with ledger:
            ev = evaluate_ledger(ledger, registry, self.clock())
        for k in ("settled", "outstanding", "events", "data_quality_issues"):
            ev[f"{k}_count"] = len(ev.pop(k))
        ev["attribution"] = DATA_ATTRIBUTION
        return 200, ev

    def fixtures(self, params):
        days = _int(params, "days", 60, 1, 60)
        now = self.clock()
        try:
            doc = json.loads(self.fixtures_path.read_text(encoding="utf-8"))
            listed = doc["fixtures"]
        except FileNotFoundError:
            return 200, {"available": False, "fixtures": [], "count": 0, "generated_at": now.isoformat(),
                         "message": "The fixture list has not been published yet; it is written by the next "
                                    "scheduled forecast run.", "attribution": DATA_ATTRIBUTION}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.error("fixture list unreadable: %s", exc)
            raise ApiError(503, "fixtures_unavailable", "fixture list unreadable")
        ledger, registry, checks = self._serving_ledger()
        with ledger:
            forecast_keys = {p["fixture_key"] for p in ledger.predictions()}
        items = []
        for f in listed:
            try:
                kickoff = datetime.fromisoformat(f["kickoff_utc"])
            except (KeyError, TypeError, ValueError):
                continue
            if not now < kickoff <= now + timedelta(days=days):
                continue
            if f.get("fixture_key") in forecast_keys:
                state = "forecast_published"
            elif kickoff > now + timedelta(hours=MIN_LEAD_HOURS):
                state = "awaiting_forecast"
            else:
                state = "not_forecast"   # inside 48 h with no recorded forecast: none will be made
            items.append({"fixture_key": f.get("fixture_key"), "kickoff_at_listed": f["kickoff_utc"],
                          "home": f.get("home"), "away": f.get("away"), "forecast_status": state})
        return 200, {"available": True, "generated_at": now.isoformat(), "list_generated_at": doc.get("generated_at"),
                     "source": doc.get("source"), "count": len(items), "window_days": days, "fixtures": items,
                     "note": "Kickoff times are listed (OpenFootball) times and may differ from the actual kickoff. "
                             "Forecasts are published 2 to 7 days before kickoff by the scheduled run.",
                     "attribution": DATA_ATTRIBUTION}

    def metrics_text(self) -> str:
        gauges: Dict[str, float] = {}
        try:
            with self._open() as ledger:
                gauges["alea_ledger_champion_forecasts"] = len(ledger.predictions())
                runs = [r for r in ledger.runs() if r["status"] == "ok"]
                if runs:
                    gauges["alea_last_successful_run_age_seconds"] = round(
                        (self.clock() - datetime.fromisoformat(runs[-1]["started_at"])).total_seconds())
                gauges["alea_ledger_available"] = 1
        except ApiError:
            gauges["alea_ledger_available"] = 0
        return self.metrics.render(gauges)

    # ------------------------------------------------------------- WSGI
    def route(self, method: str, path: str, query: str) -> Tuple[int, Any, str]:
        params = parse_qs(query, keep_blank_values=True)
        if method not in ("GET", "HEAD"):
            raise ApiError(405, "method_not_allowed", "only GET is supported")
        if path == "/health":
            return (*self.health(params), "health")
        if path == "/metrics":
            return 200, self.metrics_text(), "metrics"
        if path == "/v1/status":
            return (*self.status(params), "status")
        if path == "/v1/predictions/upcoming":
            return (*self.upcoming(params), "upcoming")
        if path == "/v1/predictions/history":
            return (*self.history(params), "history")
        if path == "/v1/evaluation":
            return (*self.evaluation(params), "evaluation")
        if path == "/v1/fixtures/upcoming":
            return (*self.fixtures(params), "fixtures")
        if path.startswith("/v1/predictions/"):
            return (*self.one(unquote(path[len("/v1/predictions/"):])), "prediction")
        raise ApiError(404, "not_found", f"no route {path}")

    def __call__(self, environ, start_response) -> Iterable[bytes]:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        route = "unknown"
        static = self.static.get(path) if method in ("GET", "HEAD") else None
        if static is not None:
            payload, ctype = static
            elapsed = time.perf_counter() - started
            self.metrics.observe("static", 200, elapsed)
            # The service worker must revalidate so a new release reaches installed apps.
            start_response("200 OK", [("Content-Type", ctype), ("Content-Length", str(len(payload))),
                                      ("Cache-Control", "no-cache"), ("X-Request-Id", request_id),
                                      *SECURITY_HEADERS])
            return [b"" if method == "HEAD" else payload]
        try:
            status, body, route = self.route(method, path, environ.get("QUERY_STRING", ""))
        except ApiError as exc:
            status, body = exc.status, {"error": {"code": exc.code, "message": exc.message}}
        except Exception:  # never leak internals; log them
            log.exception("unhandled error request_id=%s", request_id)
            status, body = 500, {"error": {"code": "internal_error", "message": "internal error",
                                           "request_id": request_id}}
        if isinstance(body, str):
            payload, ctype = body.encode(), "text/plain; version=0.0.4; charset=utf-8"
        else:
            payload, ctype = (json.dumps(body, indent=2, default=str) + "\n").encode(), "application/json"
        elapsed = time.perf_counter() - started
        self.metrics.observe(route, status, elapsed)
        log.info(json.dumps({"request_id": request_id, "method": method, "path": path, "status": status,
                             "duration_ms": round(elapsed * 1000, 2)}))
        start_response(f"{status} {_REASONS.get(status, 'Error')}",
                       [("Content-Type", ctype), ("Content-Length", str(len(payload))),
                        ("X-Request-Id", request_id), ("Cache-Control", "no-store"),
                        *SECURITY_HEADERS])
        return [b"" if method == "HEAD" else payload]
