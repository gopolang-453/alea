"""Release 1.0 web app: static serving, security headers, fixture list, and the
expected-goals / scoreline fields recorded for new forecasts."""
import json
import re
import shutil
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_prospective_forecast as pipeline  # noqa: E402
from scripts.serve_api import QuietHandler, ThreadingWSGIServer  # noqa: E402
from stages.stage11.api import CSP, ForecastAPI  # noqa: E402
from stages.stage9.prospective_ledger import ProspectiveLedger  # noqa: E402
from tests.prospective_synth import argv, build  # noqa: E402
from tests.test_stage11_api import call  # noqa: E402
from wsgiref.simple_server import make_server  # noqa: E402

RUN_AT = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
WEB = ROOT / "web"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = build(tmp_path_factory.mktemp("web"))
    assert pipeline.main(argv(e, RUN_AT.isoformat(), "--init-ledger")) == 0
    return e


def _app(env, now=RUN_AT + timedelta(hours=1), **kw):
    kw.setdefault("fixtures_path", env["out"] / "fixtures_upcoming.json")
    return ForecastAPI(env["ledger"], env["registry"], root=ROOT, clock=lambda: now, **kw)


# ---------------------------------------------------------------- recorded detail
def test_new_forecasts_record_expected_goals_and_scorelines(env):
    with ProspectiveLedger(env["ledger"], read_only=True) as ledger:
        rows = ledger.predictions()
    assert rows
    for p in rows:
        assert p["expected_goals_home"] > 0 and p["expected_goals_away"] > 0
        scores = json.loads(p["payload_json"])["extra"]["top_scorelines"]
        assert len(scores) == 5
        probs = [s["probability"] for s in scores]
        assert probs == sorted(probs, reverse=True) and 0 < sum(probs) < 1
        assert all(re.fullmatch(r"\d+-\d+", s["score"]) for s in scores)


def test_detail_mismatch_blocks_recording(tmp_path, monkeypatch):
    """If predict() ever disagreed with the recorded 1X2 the run is blocked, nothing written."""
    e = build(tmp_path)
    real = pipeline.champion_detail

    def skewed(*a, **k):
        d = real(*a, **k)
        d["p_1x2"] = [d["p_1x2"][0] + 0.01, d["p_1x2"][1] - 0.01, d["p_1x2"][2]]
        return d
    monkeypatch.setattr(pipeline, "champion_detail", skewed)
    assert pipeline.main(argv(e, RUN_AT.isoformat(), "--init-ledger")) == 2
    with ProspectiveLedger(e["ledger"], read_only=True) as ledger:
        assert ledger.predictions() == []


def test_existing_forecasts_are_not_backfilled(env, tmp_path):
    """A forecast recorded without detail keeps null detail on later runs."""
    e = build(tmp_path)
    assert pipeline.main(argv(e, RUN_AT.isoformat(), "--init-ledger")) == 0
    con = sqlite3.connect(e["ledger"])
    before = con.execute("SELECT fixture_key, payload_json, expected_goals_home FROM predictions ORDER BY 1").fetchall()
    con.close()
    assert pipeline.main(argv(e, (RUN_AT + timedelta(hours=6)).isoformat())) == 0
    con = sqlite3.connect(e["ledger"])
    after = con.execute("SELECT fixture_key, payload_json, expected_goals_home FROM predictions ORDER BY 1").fetchall()
    con.close()
    assert after == before


def test_api_exposes_detail_and_null_for_legacy_rows(env, tmp_path):
    status, body, _ = call(_app(env), "/v1/predictions/upcoming", "days=7")
    assert status == 200
    for p in body["predictions"]:
        assert set(p["expected_goals"]) == {"home", "away"}
        assert len(p["top_scorelines"]) == 5
    # Legacy row: copy the ledger and strip the detail through a fresh ledger with a v1-style row.
    legacy = tmp_path / "ledger.sqlite"
    with ProspectiveLedger(legacy, create=True) as led:
        led.record_prediction(fixture_key="2026-11-14|arsenal|chelsea", predicted_at=RUN_AT,
                              kickoff_at=RUN_AT + timedelta(days=4), p_home=0.5, p_draw=0.3, p_away=0.2,
                              model_version="alea-dc-v2.4.1", extra={"xi": 0.0018})
    app = ForecastAPI(legacy, env["registry"], root=ROOT, clock=lambda: RUN_AT + timedelta(hours=1))
    status, body, _ = call(app, "/v1/predictions/" + "2026-11-14%7Carsenal%7Cchelsea")
    assert status == 200 and body["expected_goals"] is None and body["top_scorelines"] is None


# ---------------------------------------------------------------- fixture list
def test_pipeline_publishes_fixture_list(env):
    doc = json.loads((env["out"] / "fixtures_upcoming.json").read_text())
    assert doc["licence"].startswith("CC0") and doc["source"]["sha256"]
    kicks = [f["kickoff_utc"] for f in doc["fixtures"]]
    assert kicks == sorted(kicks) and all(k > RUN_AT.isoformat() for k in kicks)
    assert not list(env["out"].glob("*.tmp"))


def test_fixtures_endpoint_marks_forecast_status(env):
    status, body, _ = call(_app(env), "/v1/fixtures/upcoming", "days=60")
    assert status == 200 and body["available"] and body["count"] > 10
    states = {f["forecast_status"] for f in body["fixtures"]}
    assert "forecast_published" in states and "awaiting_forecast" in states
    with ProspectiveLedger(env["ledger"], read_only=True) as ledger:
        keys = {p["fixture_key"] for p in ledger.predictions()}
    for f in body["fixtures"]:
        assert (f["forecast_status"] == "forecast_published") == (f["fixture_key"] in keys)


def test_fixtures_endpoint_handles_missing_and_corrupt_file(env, tmp_path):
    status, body, _ = call(_app(env, fixtures_path=tmp_path / "nope.json"), "/v1/fixtures/upcoming")
    assert status == 200 and body["available"] is False and body["fixtures"] == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    status, body, _ = call(_app(env, fixtures_path=bad), "/v1/fixtures/upcoming")
    assert status == 503 and body["error"]["code"] == "fixtures_unavailable"
    assert str(tmp_path) not in json.dumps(body)
    status, body, _ = call(_app(env), "/v1/fixtures/upcoming", "days=0")
    assert status == 400


# ---------------------------------------------------------------- static app
def test_index_served_with_security_headers(env):
    status, body, hdr = call(_app(env), "/")
    h = hdr["headers"]
    assert status == 200 and h["Content-Type"].startswith("text/html")
    assert "<title>ALEA" in body
    assert h["Content-Security-Policy"] == CSP and "frame-ancestors 'none'" in CSP
    assert "'unsafe-inline'" not in CSP and "'unsafe-eval'" not in CSP
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "no-referrer"


def test_api_responses_carry_security_headers(env):
    _, _, hdr = call(_app(env), "/v1/status")
    assert hdr["headers"]["Content-Security-Policy"] == CSP
    assert hdr["headers"]["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path,ctype", [("/assets/app.js", "text/javascript"), ("/assets/app.css", "text/css"),
                                        ("/manifest.webmanifest", "application/manifest+json"),
                                        ("/sw.js", "text/javascript"), ("/icons/icon-192.png", "image/png"),
                                        ("/fonts/archivo-latin-var.woff2", "font/woff2")])
def test_static_assets(env, path, ctype):
    app = _app(env)
    payload = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": ""},
                           lambda s, h: captured.update(status=s, headers=dict(h))))
    assert captured["status"].startswith("200") and captured["headers"]["Content-Type"].startswith(ctype)
    assert payload == (WEB / path.lstrip("/")).read_bytes()


captured: dict = {}


@pytest.mark.parametrize("path", ["/../config/model_registry.json", "/..%2f..%2fetc/passwd", "/assets/../../Dockerfile",
                                  "/%2e%2e/alea_predictor_v2_4_1.py", "/config/model_registry.json",
                                  "/web/index.html", "/.git/config", "/assets/", "//etc/passwd"])
def test_no_path_traversal_or_arbitrary_files(env, path):
    status, body, _ = call(_app(env), path)
    assert status == 404
    assert "error" in body and "/" + "home" not in json.dumps(body)


def test_static_rejects_post_and_head_has_no_body(env):
    status, _, _ = call(_app(env), "/", method="POST")
    assert status == 405
    app = _app(env)
    out = b"".join(app({"REQUEST_METHOD": "HEAD", "PATH_INFO": "/", "QUERY_STRING": ""}, lambda s, h: None))
    assert out == b""


def test_web_dir_can_be_disabled(env):
    status, _, _ = call(_app(env, web_dir=None), "/")
    assert status == 404


def test_static_allowlist_skips_symlinks_and_dotfiles(env, tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<title>ALEA</title>")
    (web / ".secret.txt").write_text("x")
    (web / "notes.py").write_text("print(1)")
    (web / "assets" / "link.txt").symlink_to(ROOT / "config" / "model_registry.json")
    app = _app(env, web_dir=web)
    assert set(app.static) == {"/", "/index.html"}


# ---------------------------------------------------------------- front-end contract
def test_frontend_has_no_inline_script_or_style_and_no_external_hosts():
    html = (WEB / "index.html").read_text()
    js = (WEB / "assets" / "app.js").read_text()
    css = (WEB / "assets" / "app.css").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "inline <script> would be blocked by the CSP"
    assert "style=" not in html and 'style="' not in js and "style='" not in js
    for text in (html, css):
        assert not re.search(r"(src|href)=\"https?://(?!en\.wikipedia|creativecommons|github\.com)", text)
    assert "@import" not in css and "url(http" not in css
    assert "fetch(API + path" in js and "Math.random" not in js


def test_frontend_rounding_always_sums_to_100():
    """Port of pct3() (largest remainder) checked against many probability triples."""
    import random
    rng = random.Random(3)

    def pct3(p):
        raw = [x * 100 for x in p]
        fl = [int(x // 1) for x in raw]
        left = 100 - sum(fl)
        order = sorted(range(3), key=lambda i: raw[i] - fl[i], reverse=True)
        for i in order[:left]:
            fl[i] += 1
        return fl

    js = (WEB / "assets" / "app.js").read_text()
    assert "Largest-remainder rounding" in js
    for _ in range(5000):
        a, b = sorted(rng.random() for _ in range(2))
        r = pct3([a, b - a, 1 - b])
        assert sum(r) == 100 and all(x >= 0 for x in r)
    assert pct3([0.3333, 0.3333, 0.3334]) == [33, 33, 34]


def test_service_worker_never_caches_forecast_data():
    sw = (WEB / "sw.js").read_text()
    assert "/v1/" in sw and "return;" in sw
    shell = re.search(r"SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "v1" not in shell and "health" not in shell
    for item in re.findall(r"'([^']+)'", shell):
        assert item == "./" or (WEB / item).is_file(), item


def test_manifest_icons_exist():
    m = json.loads((WEB / "manifest.webmanifest").read_text())
    assert m["display"] == "standalone" and m["short_name"] == "ALEA"
    for icon in m["icons"]:
        assert (WEB / icon["src"]).is_file()


def test_real_http_server_serves_app_and_api(env):
    app = _app(env)
    server = make_server("127.0.0.1", 0, app, server_class=ThreadingWSGIServer, handler_class=QuietHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/") as r:
            assert r.status == 200 and b"ALEA" in r.read()
            assert "default-src 'self'" in r.headers["Content-Security-Policy"]
        with urllib.request.urlopen(base + "/v1/fixtures/upcoming") as r:
            assert json.loads(r.read())["available"] is True
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/../../etc/passwd")
        assert exc.value.code == 404
    finally:
        server.shutdown()
