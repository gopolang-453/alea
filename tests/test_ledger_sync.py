"""Hosted-instance ledger sync: only gate-verified, append-only successors are served."""
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_prospective_forecast as pipeline  # noqa: E402
from stages.stage11.api import ForecastAPI  # noqa: E402
from stages.stage11.ledger_sync import LedgerSync  # noqa: E402
from tests.prospective_synth import argv, build  # noqa: E402
from tests.test_stage11_api import call  # noqa: E402

RUN_AT = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def upstream(tmp_path_factory):
    """Two successive real pipeline runs: v1 is the first ledger, v2 its append-only successor."""
    e = build(tmp_path_factory.mktemp("up"))
    assert pipeline.main(argv(e, RUN_AT.isoformat(), "--init-ledger")) == 0
    v1 = e["ledger"].read_bytes()
    fx1 = (e["out"] / "fixtures_upcoming.json").read_bytes()
    assert pipeline.main(argv(e, (RUN_AT + timedelta(hours=3)).isoformat())) == 0
    return {"v1": v1, "v2": e["ledger"].read_bytes(), "fx": fx1, "env": e}


def _sync(tmp_path, files):
    def fetch(url):
        name = url.rsplit("/", 1)[-1]
        if isinstance(files.get(name), Exception):
            raise files[name]
        if name not in files:
            raise OSError("404")
        return files[name]
    return LedgerSync("https://example.invalid/data", tmp_path / "serve" / "ledger.sqlite",
                      tmp_path / "serve" / "fixtures_upcoming.json", fetch=fetch)


def test_initial_sync_and_append_only_update(upstream, tmp_path):
    files = {"ledger.sqlite": upstream["v1"], "fixtures_upcoming.json": upstream["fx"]}
    s = _sync(tmp_path, files)
    r = s.sync_once()
    assert r["last_error"] is None and set(r["changed"]) == {"ledger", "fixtures"}
    assert s.ledger_path.read_bytes() == upstream["v1"]
    assert s.sync_once()["changed"] == []            # identical: no-op
    files["ledger.sqlite"] = upstream["v2"]
    assert s.sync_once()["changed"] == ["ledger"]
    assert s.ledger_path.read_bytes() == upstream["v2"]
    assert not list(s.ledger_path.parent.glob("*.download"))


def test_rollback_or_tampered_ledger_is_refused(upstream, tmp_path):
    files = {"ledger.sqlite": upstream["v2"]}
    s = _sync(tmp_path, files)
    s.sync_once()
    # Rollback to an older ledger (rows removed) is refused.
    files["ledger.sqlite"] = upstream["v1"]
    r = s.sync_once()
    assert r["last_error"] and s.ledger_path.read_bytes() == upstream["v2"]
    # A rewritten forecast (trigger dropped, probability edited) is refused.
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(upstream["v2"])
    con = sqlite3.connect(bad)
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        con.execute(f'DROP TRIGGER "{name}"')
    con.execute("UPDATE predictions SET p_home=p_home+0.01, p_away=p_away-0.01")
    con.commit()
    con.close()
    files["ledger.sqlite"] = bad.read_bytes()
    r = s.sync_once()
    assert r["last_error"] and s.ledger_path.read_bytes() == upstream["v2"]


def test_garbage_and_network_errors_keep_last_copy(upstream, tmp_path):
    files = {"ledger.sqlite": upstream["v1"]}
    s = _sync(tmp_path, files)
    s.sync_once()
    files["ledger.sqlite"] = b"not a database" * 100
    assert s.sync_once()["last_error"]
    files["ledger.sqlite"] = OSError("connection reset")
    assert s.sync_once()["last_error"]
    assert s.ledger_path.read_bytes() == upstream["v1"]
    assert not list(s.ledger_path.parent.glob("*.download"))


def test_first_sync_refuses_corrupt_ledger(tmp_path):
    s = _sync(tmp_path, {"ledger.sqlite": b"\x00" * 4096})
    assert s.sync_once()["last_error"] and not s.ledger_path.exists()


def test_bad_fixture_list_does_not_block_ledger(upstream, tmp_path):
    s = _sync(tmp_path, {"ledger.sqlite": upstream["v1"], "fixtures_upcoming.json": b"{oops"})
    r = s.sync_once()
    assert r["last_error"] is None and r["changed"] == ["ledger"] and not s.fixtures_path.exists()


def test_health_reports_sync_failure_as_degraded(upstream, tmp_path):
    files = {"ledger.sqlite": upstream["v1"]}
    s = _sync(tmp_path, files)
    s.sync_once()
    app = ForecastAPI(s.ledger_path, upstream["env"]["registry"], root=ROOT, sync_status=s.status,
                      clock=lambda: RUN_AT + timedelta(hours=1))
    status, body, _ = call(app, "/health")
    assert status == 200 and body["status"] == "ok" and body["ledger_sync"]["last_error"] is None
    files["ledger.sqlite"] = OSError("down")
    s.sync_once()
    status, body, _ = call(app, "/health")
    assert body["status"] == "degraded" and "example.invalid" not in json.dumps(body)


def test_only_https_sources():
    from stages.stage11.ledger_sync import _download
    with pytest.raises(ValueError):
        _download("http://raw.githubusercontent.com/x")
    with pytest.raises(ValueError):
        _download("file:///etc/passwd")
