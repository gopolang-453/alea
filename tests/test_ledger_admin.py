import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ledger_admin import main  # noqa: E402
from stages.stage9.prospective_ledger import ProspectiveLedger  # noqa: E402

KEY = "2027-01-02|team a|team b"


def _ledger(path):
    with ProspectiveLedger(path) as led:
        led.record_prediction(fixture_key=KEY, predicted_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
                              kickoff_at=datetime(2027, 1, 2, 15, tzinfo=timezone.utc),
                              p_home=0.5, p_draw=0.25, p_away=0.25, model_version="m")
        return led.fingerprint()


def test_events_and_backup_restore_do_not_change_forecasts(tmp_path, capsys):
    path = tmp_path / "l.sqlite"
    fp = _ledger(path)
    assert main(["--ledger", str(path), "event", KEY, "POSTPONED", "--source", "club statement"]) == 0
    assert main(["--ledger", str(path), "event", KEY, "POSTPONED", "--source", "club statement"]) == 0
    assert "already recorded" in capsys.readouterr().out
    assert main(["--ledger", str(path), "event", KEY, "RESCHEDULED", "--source", "x"]) == 1  # needs --new-kickoff
    assert main(["--ledger", str(path), "event", "2027-01-09|x|y", "VOID", "--source", "x"]) == 1
    assert main(["--ledger", str(path), "backup", "--dir", str(tmp_path / "b")]) == 0
    backup = next((tmp_path / "b").glob("ledger_*.sqlite"))
    assert main(["--ledger", str(tmp_path / "restored.sqlite"), "restore", str(backup)]) == 0
    with ProspectiveLedger(tmp_path / "restored.sqlite", read_only=True) as led:
        assert led.fingerprint() == fp and len(led.events(KEY)) == 1
    assert main(["--ledger", str(path), "integrity"]) == 0


def test_missing_ledger_is_not_created(tmp_path):
    target = tmp_path / "none.sqlite"
    assert main(["--ledger", str(target), "status"]) == 3
    assert not target.exists()
