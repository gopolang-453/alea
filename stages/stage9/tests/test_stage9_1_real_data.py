"""
Stage 9.1 — Connect real historical Premier League data.
Uses the existing Stage 1 CSV importer. Does not create a new one.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "alea_stage1"))

from persistent_store import PersistentDataStore, ingest_csv


DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "epl"
SEASONS = ["E0_1920.csv", "E0_2021.csv", "E0_2122.csv", "E0_2223.csv", "E0_2324.csv"]


class TestStage91RealData:
    def test_import_real_seasons_and_no_duplicates_on_second_import(self, tmp_path):
        db = tmp_path / "alea_epl.db"
        with PersistentDataStore(db) as store:
            total_first = 0
            for name in SEASONS:
                path = DATA_DIR / name
                assert path.exists(), f"missing {path}"
                total_first += ingest_csv(store, path)
            assert total_first == 1900  # 5 seasons × 380
            # Snapshot retrieves the data
            snap = store.snapshot(datetime(2025, 1, 1, tzinfo=timezone.utc))
            frame = snap.to_results_frame()
            assert len(frame) == 1900
            # Basic validity
            assert (frame["FTHG"] >= 0).all()
            assert (frame["FTAG"] >= 0).all()
            assert frame["HomeTeam"].notna().all()
            assert frame["AwayTeam"].notna().all()
            # No duplicate fixture keys
            keys = set()
            for r in store.all_records():
                if r.kind == "result":
                    assert r.fixture_key not in keys
                    keys.add(r.fixture_key)
            assert len(keys) == 1900

            # Second import of the same files must add zero rows
            total_second = 0
            for name in SEASONS:
                total_second += ingest_csv(store, DATA_DIR / name)
            assert total_second == 0
            assert len([r for r in store.all_records() if r.kind == "result"]) == 1900

            # Reopen and confirm still 1900
            fp = store.fingerprint()
        with PersistentDataStore(db) as store2:
            assert store2.fingerprint() == fp
            snap2 = store2.snapshot(datetime(2025, 1, 1, tzinfo=timezone.utc))
            assert len(snap2.to_results_frame()) == 1900


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
