"""
Stage 9.1 ingestion smoke test.

This test deliberately uses a small checked-in CSV fixture. It verifies the
Stage 1 persistence contract, not the separate 1,900-match historical report.
The full historical experiment requires a separately licensed, manifested data
bundle and is not claimed as reproducible by this test.
"""

from datetime import datetime, timezone
from pathlib import Path

from stages.stage1.data_store import PersistentDataStore, ingest_csv


FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "epl_sample.csv"


def test_stage91_csv_import_is_persistent_and_idempotent(tmp_path):
    database = tmp_path / "stage9.sqlite"
    with PersistentDataStore(database) as store:
        first = ingest_csv(store, FIXTURE)
        assert first == 3
        snapshot = store.snapshot(datetime(2024, 8, 21, 12, tzinfo=timezone.utc))
        frame = snapshot.to_results_frame()
        assert len(frame) == 3
        assert (frame["FTHG"] >= 0).all()
        assert (frame["FTAG"] >= 0).all()
        assert frame["HomeTeam"].notna().all()
        assert frame["AwayTeam"].notna().all()

        fingerprint = store.fingerprint()
        assert ingest_csv(store, FIXTURE) == 0
        assert len(store.all_records()) == 3

    with PersistentDataStore(database) as reopened:
        assert reopened.fingerprint() == fingerprint
        assert len(reopened.snapshot(
            datetime(2024, 8, 21, 12, tzinfo=timezone.utc)
        ).to_results_frame()) == 3
