"""Stage 12: ledger backup/restore and the ledger + service drill."""
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.recovery_drill import run_ledger_drill  # noqa: E402
from stages.stage12.ledger_ops import backup_ledger, restore_ledger, verify_backup  # noqa: E402
from stages.stage12.reliability import ReliabilityError  # noqa: E402
from stages.stage9.prospective_ledger import ProspectiveLedger  # noqa: E402

REAL = ROOT / "results" / "prospective" / "ledger.sqlite"
REGISTRY = ROOT / "config" / "model_registry.json"


def _ledger(path, n=3):
    with ProspectiveLedger(path) as led:
        for i in range(n):
            led.record_prediction(fixture_key=f"2027-01-0{i + 1}|team a{i}|team b{i}",
                                  predicted_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
                                  kickoff_at=datetime(2027, 1, i + 1, 15, tzinfo=timezone.utc),
                                  p_home=0.5, p_draw=0.25, p_away=0.25, model_version="m")
        return led.fingerprint()


def test_backup_verify_restore_roundtrip(tmp_path):
    src = tmp_path / "l.sqlite"
    fp = _ledger(src)
    manifest = backup_ledger(src, tmp_path / "b")
    backup = tmp_path / "b" / manifest["backup"]
    assert verify_backup(backup, manifest)["ok"] and manifest["fingerprint"] == fp
    dest = tmp_path / "r.sqlite"
    assert restore_ledger(backup, manifest, dest)["fingerprint"] == fp


def test_restore_refuses_tampered_backup_and_history_loss(tmp_path):
    src = tmp_path / "l.sqlite"
    _ledger(src, 2)
    manifest = backup_ledger(src, tmp_path / "b")
    backup = tmp_path / "b" / manifest["backup"]
    _ledger(src, 3)  # adds a third forecast (first two already present -> idempotent)
    with pytest.raises(ReliabilityError, match="lacks"):
        restore_ledger(backup, manifest, src)
    data = bytearray(backup.read_bytes())
    data[len(data) // 2] ^= 0xFF
    backup.write_bytes(bytes(data))
    with pytest.raises(ReliabilityError, match="refusing"):
        restore_ledger(backup, manifest, tmp_path / "x.sqlite")


def test_backup_of_missing_or_corrupt_store_fails(tmp_path):
    with pytest.raises(ReliabilityError):
        backup_ledger(tmp_path / "none.sqlite", tmp_path / "b")
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"garbage" * 100)
    with pytest.raises(Exception):
        backup_ledger(bad, tmp_path / "b")


@pytest.mark.skipif(not REAL.exists(), reason="real ledger not present")
def test_ledger_drill_on_real_store_passes_and_leaves_it_untouched(tmp_path):
    before = REAL.read_bytes()
    report = run_ledger_drill(REAL, tmp_path, registry=REGISTRY)
    assert report["passed"], (report["checks"], report["details"])
    assert len(report["checks"]) == 17
    assert REAL.read_bytes() == before


def test_ledger_drill_fails_on_corrupt_store(tmp_path):
    src = tmp_path / "l.sqlite"
    _ledger(src)
    shutil.copy2(src, tmp_path / "c.sqlite")
    (tmp_path / "c.sqlite").write_bytes(b"x" * 4096)
    with pytest.raises(Exception):
        run_ledger_drill(tmp_path / "c.sqlite", tmp_path / "s", registry=REGISTRY)


def test_restore_refuses_backup_missing_outcomes_or_observations(tmp_path):
    """Audit: history-loss protection must cover every table, not only champion forecasts."""
    from datetime import datetime, timezone
    from stages.stage12.ledger_ops import backup_ledger, restore_ledger
    from stages.stage12.reliability import ReliabilityError
    from stages.stage9.prospective_ledger import ProspectiveLedger
    import pytest
    live = tmp_path / "ledger.sqlite"
    utc = timezone.utc
    with ProspectiveLedger(live) as led:
        led.record_prediction(fixture_key="2026-12-05|a fc|b fc", predicted_at=datetime(2026, 12, 1, tzinfo=utc),
                              kickoff_at=datetime(2026, 12, 5, 15, tzinfo=utc), p_home=0.5, p_draw=0.3,
                              p_away=0.2, model_version="alea-dc-v2.4.1")
    manifest = backup_ledger(live, tmp_path / "b")
    with ProspectiveLedger(live) as led:  # later: the match is settled
        led.observe_and_settle("2026-12-05|a fc|b fc", [("wikipedia", 2, 1, "r1")],
                               datetime(2026, 12, 6, tzinfo=utc))
        settled = led.get_outcome("2026-12-05|a fc|b fc")
    assert settled is not None
    before = live.read_bytes()
    with pytest.raises(ReliabilityError, match="backup lacks rows"):
        restore_ledger(tmp_path / "b" / manifest["backup"], manifest, live)
    assert live.read_bytes() == before
    restore_ledger(tmp_path / "b" / manifest["backup"], manifest, live, allow_history_loss=True)
