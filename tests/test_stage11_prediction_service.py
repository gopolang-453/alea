"""Stage 11 prediction service and history tests."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage11 import prediction_service as service


def fake_prediction(params, home, away, allow_new_teams):
    return {
        "markets": {
            "home": 0.5, "draw": 0.25, "away": 0.25,
            "over_1_5": 0.7, "over_2_5": 0.5, "over_3_5": 0.25,
            "under_2_5": 0.5, "btts_yes": 0.45, "btts_no": 0.55,
        },
        "lambda_home": 1.5, "lambda_away": 1.0,
        "most_likely_score": "1-0", "top_scores": [("1-0", 0.15), ("1-1", 0.12)],
        "tail_probability": 1e-8, "prior_only_teams": [],
        "rho_clipped_for_pair": False,
    }


def params():
    return {
        "teams": ["Arsenal", "Chelsea"],
        "data_through": "2024-01-01",
        "as_of_date": "2024-01-02",
        "model_version": "test-model",
        "n_matches_trained": 1000,
    }


def test_prediction_response_contains_provenance_and_probabilities(monkeypatch):
    monkeypatch.setattr(service.dc, "predict", fake_prediction)
    response = service.build_prediction(
        params(), "Arsenal", "Chelsea", date(2024, 2, 1),
        datetime(2024, 1, 31, 12, tzinfo=timezone.utc), "a" * 64,
    )
    assert response["probabilities_1x2"] == {"home": 0.5, "draw": 0.25, "away": 0.25}
    assert response["model"]["version"] == "test-model"
    assert response["data_snapshot_sha256"] == "a" * 64
    assert response["top_scorelines"][0]["score"] == "1-0"
    assert "matrix" not in response


def test_prediction_history_is_persistent_and_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(service.dc, "predict", fake_prediction)
    response = service.build_prediction(
        params(), "Arsenal", "Chelsea", date(2024, 2, 1),
        datetime(2024, 1, 31, 12, tzinfo=timezone.utc), "b" * 64,
    )
    db = tmp_path / "history.sqlite"
    with service.PredictionHistory(db) as history:
        prediction_id = history.save(response)
        assert history.save(response) == prediction_id
        assert history.count() == 1
    with service.PredictionHistory(db) as reopened:
        assert reopened.get(prediction_id) == response


def test_prediction_rejects_unknown_teams_and_same_day_without_kickoff(monkeypatch):
    monkeypatch.setattr(service.dc, "predict", fake_prediction)
    with pytest.raises(ValueError, match="unknown team"):
        service.build_prediction(
            params(), "Arsenal", "New Team", date(2024, 2, 1),
            datetime(2024, 1, 31, 12, tzinfo=timezone.utc), "c" * 64,
        )
    with pytest.raises(ValueError, match="before fixture day"):
        service.build_prediction(
            params(), "Arsenal", "Chelsea", date(2024, 2, 1),
            datetime(2024, 2, 1, 8, tzinfo=timezone.utc), "c" * 64,
        )


def test_prediction_requires_prediction_before_kickoff_and_valid_model_cutoff(monkeypatch):
    monkeypatch.setattr(service.dc, "predict", fake_prediction)
    with pytest.raises(ValueError, match="before kickoff"):
        service.build_prediction(
            params(), "Arsenal", "Chelsea", date(2024, 2, 1),
            datetime(2024, 2, 1, 16, tzinfo=timezone.utc), "d" * 64,
            kickoff_at=datetime(2024, 2, 1, 15, tzinfo=timezone.utc),
        )
    bad = params()
    bad["data_through"] = "2024-02-01"
    with pytest.raises(ValueError, match="fixture date"):
        service.build_prediction(
            bad, "Arsenal", "Chelsea", date(2024, 2, 1),
            datetime(2024, 1, 31, 12, tzinfo=timezone.utc), "d" * 64,
        )
