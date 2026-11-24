"""Stage 11 HTTP API tests (in-process WSGI and a real socket server)."""
import io
import json
import shutil
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_prospective_forecast as pipeline  # noqa: E402
from scripts.serve_api import QuietHandler, ThreadingWSGIServer  # noqa: E402
from stages.stage11.api import ForecastAPI  # noqa: E402
from tests.prospective_synth import argv, build  # noqa: E402
from wsgiref.simple_server import make_server  # noqa: E402

RUN_AT = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = build(tmp_path_factory.mktemp("api"))
    assert pipeline.main(argv(e, RUN_AT.isoformat(), "--init-ledger")) == 0
    return e


def _app(env, *, ledger=None, registry=None, now=RUN_AT + timedelta(hours=1), **kw):
    return ForecastAPI(ledger or env["ledger"], registry or env["registry"], root=ROOT,
                       clock=lambda: now, **kw)


def call(app, path, query="", method="GET"):
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
                         "wsgi.input": io.BytesIO()}, start_response))
    ctype = captured["headers"]["Content-Type"]
    return captured["status"], (json.loads(body) if ctype == "application/json" else body.decode()), captured


def test_health_ok_with_freshness(env):
    status, body, hdr = call(_app(env), "/health")
    assert status == 200 and body["status"] == "ok", body
    assert body["champion"] == "alea-dc-v2.4.1"
    assert body["freshness"]["last_successful_run_at"].startswith("2026-11-10T12:00")
    assert body["integrity"]["ok"] and body["integrity"]["champion_forecasts"] == 10
    assert "X-Request-Id" in hdr["headers"]


def test_health_degraded_when_runs_are_stale(env):
    status, body, _ = call(_app(env, now=RUN_AT + timedelta(days=12)), "/health")
    assert status == 200 and body["status"] == "degraded"
    assert any("old" in w for w in body["warnings"])


def test_upcoming_predictions(env):
    status, body, _ = call(_app(env), "/v1/predictions/upcoming", "days=7")
    assert status == 200 and body["count"] == 10
    for p in body["predictions"]:
        probs = p["probabilities"]
        assert abs(probs["home"] + probs["draw"] + probs["away"] - 1) < 1e-9
        assert p["model_version"] == "alea-dc-v2.4.1"
        assert p["predicted_at"].startswith("2026-11-10T12:00")
        assert len(p["training_data_sha256"]) == 64
        assert "challengers" not in p
    status, body, _ = call(_app(env), "/v1/predictions/upcoming", "include_challengers=true")
    assert {c["model_id"] for c in body["predictions"][0]["challengers"]} == {"elo_ordered_logit",
                                                                              "dc_elo_equal_average"}
    # After kickoff the fixtures are no longer "upcoming".
    status, body, _ = call(_app(env, now=RUN_AT + timedelta(days=5)), "/v1/predictions/upcoming")
    assert body["count"] == 0


def test_history_and_single_fixture(env):
    status, body, _ = call(_app(env), "/v1/predictions/history", "team=arsenal")
    assert status == 200 and body["total"] == 1
    item = body["predictions"][0]
    assert item["status"] == "pending"
    status, one, _ = call(_app(env), "/v1/predictions/" + quote(item["fixture_key"], safe=""))
    assert status == 200 and one["fixture_key"] == item["fixture_key"] and len(one["challengers"]) == 2
    status, body, _ = call(_app(env), "/v1/predictions/history", "status=pending&limit=3&offset=2")
    assert body["total"] == 10 and len(body["predictions"]) == 3


@pytest.mark.parametrize("path,query", [
    ("/v1/predictions/upcoming", "days=0"),
    ("/v1/predictions/upcoming", "days=abc"),
    ("/v1/predictions/upcoming", "include_challengers=maybe"),
    ("/v1/predictions/history", "from=2026-13-01"),
    ("/v1/predictions/history", "from=2026-12-01&to=2026-11-01"),
    ("/v1/predictions/history", "status=won"),
    ("/v1/predictions/history", "limit=100000"),
    ("/v1/predictions/history", "team=%3Cscript%3E"),
    ("/v1/predictions/not-a-key", ""),
])
def test_input_validation_returns_400(env, path, query):
    status, body, _ = call(_app(env), path, query)
    assert status == 400 and body["error"]["code"] in ("invalid_parameter", "invalid_fixture_key")


def test_unknown_route_method_and_fixture(env):
    assert call(_app(env), "/nope")[0] == 404
    assert call(_app(env), "/v1/predictions/" + quote("2026-11-14|x|y", safe=""))[0] == 404
    assert call(_app(env), "/health", method="POST")[0] == 405


def test_metrics_endpoint(env):
    app = _app(env)
    call(app, "/health")
    call(app, "/nope")
    status, text, _ = call(app, "/metrics")
    assert status == 200
    assert 'alea_http_requests_total{route="health",status="200"} 1' in text
    assert 'alea_http_requests_total{route="unknown",status="404"} 1' in text
    assert "alea_ledger_champion_forecasts 10" in text


def test_refuses_to_serve_non_champion_forecasts(env, tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    shutil.copy(env["ledger"], ledger)
    con = sqlite3.connect(ledger)
    payload = json.dumps({"fixture_key": "2026-12-30|a|b", "p_home": 0.4, "p_draw": 0.3, "p_away": 0.3,
                          "model_version": "alea-dc-dev", "extra": {}}, sort_keys=True)
    con.execute("INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-12-30|a|b", "2026-12-01T00:00:00+00:00", "2026-12-30T15:00:00+00:00",
                 0.4, 0.3, 0.3, None, None, "alea-dc-dev", None, None, payload))
    con.commit()
    con.close()
    app = _app(env, ledger=ledger)
    status, body, _ = call(app, "/health")
    assert status == 503 and any("non-champion" in p for p in body["problems"])
    status, body, _ = call(app, "/v1/predictions/upcoming")
    assert status == 503 and body["error"]["code"] == "not_serving"


def test_refuses_when_champion_hash_mismatch(env, tmp_path):
    reg = json.loads(Path(env["registry"]).read_text())
    reg["champion"]["module_sha256"] = "f" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(reg))
    status, body, _ = call(_app(env, registry=path), "/v1/predictions/upcoming")
    assert status == 503


def test_missing_and_corrupt_store(env, tmp_path):
    status, body, _ = call(_app(env, ledger=tmp_path / "gone.sqlite"), "/health")
    assert status == 503 and body["status"] == "unhealthy"
    assert call(_app(env, ledger=tmp_path / "gone.sqlite"), "/v1/predictions/upcoming")[0] == 503
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"garbage" * 1000)
    assert call(_app(env, ledger=bad), "/health")[0] == 503
    assert not (tmp_path / "gone.sqlite").exists()


def test_evaluation_endpoint(env):
    status, body, _ = call(_app(env), "/v1/evaluation")
    assert status == 200 and body["counts"]["champion_forecasts"] == 10
    assert body["challengers"]["dc_elo_equal_average"]["decision"].startswith("insufficient data")


def test_real_http_server(env):
    app = _app(env)
    server = make_server("127.0.0.1", 0, app, server_class=ThreadingWSGIServer, handler_class=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/health", timeout=10) as r:
            assert r.status == 200 and json.loads(r.read())["status"] == "ok"
        with urllib.request.urlopen(base + "/v1/predictions/upcoming", timeout=10) as r:
            assert json.loads(r.read())["count"] == 10
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/v1/predictions/history?limit=0", timeout=10)
        assert err.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
