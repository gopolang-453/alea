from datetime import datetime, timedelta, timezone

import pytest

from stages.stage9.prospective_ledger import ProspectiveLedger, LedgerError


def _utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def test_prediction_before_kickoff_and_no_overwrite(tmp_path):
    db = tmp_path / "ledger.db"
    with ProspectiveLedger(db) as ledger:
        kickoff = _utc(2026, 8, 16, 15)
        predicted = kickoff - timedelta(hours=2)
        added = ledger.record_prediction(
            fixture_key="2026-08-16|arsenal|chelsea",
            predicted_at=predicted,
            kickoff_at=kickoff,
            p_home=0.55,
            p_draw=0.25,
            p_away=0.20,
            model_version="alea-dc-v2.4.1",
            data_snapshot_hash="abc",
        )
        assert added is True
        again = ledger.record_prediction(
            fixture_key="2026-08-16|arsenal|chelsea",
            predicted_at=predicted,
            kickoff_at=kickoff,
            p_home=0.55,
            p_draw=0.25,
            p_away=0.20,
            model_version="alea-dc-v2.4.1",
            data_snapshot_hash="abc",
        )
        assert again is False
        with pytest.raises(LedgerError):
            ledger.record_prediction(
                fixture_key="2026-08-16|arsenal|chelsea",
                predicted_at=predicted,
                kickoff_at=kickoff,
                p_home=0.60,
                p_draw=0.20,
                p_away=0.20,
                model_version="alea-dc-v2.4.1",
            )
        with pytest.raises(LedgerError):
            ledger.record_prediction(
                fixture_key="2026-08-17|a|b",
                predicted_at=kickoff,
                kickoff_at=kickoff,
                p_home=0.5,
                p_draw=0.25,
                p_away=0.25,
                model_version="v",
            )
        got = ledger.get_prediction("2026-08-16|arsenal|chelsea")
        assert got["p_home"] == 0.55
        assert got["model_version"] == "alea-dc-v2.4.1"


def test_outcome_recorded_once(tmp_path):
    db = tmp_path / "ledger.db"
    with ProspectiveLedger(db) as ledger:
        assert ledger.record_outcome("fix1", 2, 1, _utc(2026, 8, 16, 18)) is True
        assert ledger.record_outcome("fix1", 2, 1, _utc(2026, 8, 16, 19)) is False
        with pytest.raises(LedgerError):
            ledger.record_outcome("fix1", 1, 1, _utc(2026, 8, 16, 19))
