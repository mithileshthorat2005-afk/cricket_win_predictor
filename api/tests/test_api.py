"""
API tests for the Cricket Win Predictor FastAPI service.

Runs against the REAL model artifacts in ../models (no mocking of the ML
stack) - these are integration tests of the API contract.

Run from the repository root:
    python -m pytest api/tests -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from fastapi.testclient import TestClient

import api.app as app_module
from api.app import app


@pytest.fixture(scope="session")
def client():
    # Context manager triggers the lifespan handler => models load once
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health / metadata
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["model_loaded"] is True
    assert body["mc_engine_loaded"] is True
    assert body["players_loaded"] == 516


def test_models_loaded_once(client):
    """Models must be loaded (startup), not per request."""
    assert app_module.model is not None
    assert app_module.mc_engine is not None
    assert app_module.quality_lookup is not None and len(app_module.quality_lookup) == 516


def test_teams(client):
    r = client.get("/teams")
    assert r.status_code == 200
    teams = r.json()["teams"]
    assert len(teams) == 15
    assert "Mumbai Indians" in teams


def test_players_search(client):
    r = client.get("/players", params={"search": "kohli", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any("kohli" in p["name"].lower() for p in body["players"])
    for p in body["players"]:
        assert 0 <= p["quality"] <= 10


def test_features(client):
    r = client.get("/features", params={"top_n": 5})
    assert r.status_code == 200
    assert len(r.json()["top_features"]) == 5


# ---------------------------------------------------------------------------
# /predict (XGBoost classifier path) - contract preserved from v1.0.0
# ---------------------------------------------------------------------------

def test_predict_first_innings(client):
    r = client.post("/predict", json={
        "match_id": 1, "inning": 1,
        "batting_team": "Mumbai Indians", "bowling_team": "Chennai Super Kings",
        "overs_completed": 15.3, "runs_scored": 145, "wickets_lost": 3, "target": None
    })
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["win_probability"] <= 1.0
    assert body["inning"] == 1
    assert body["confidence"] in ("High", "Medium", "Low")
    assert isinstance(body["key_factors"], list) and len(body["key_factors"]) >= 1


def test_predict_second_innings(client):
    r = client.post("/predict", json={
        "match_id": 1, "inning": 2,
        "batting_team": "Mumbai Indians", "bowling_team": "Chennai Super Kings",
        "overs_completed": 10.2, "runs_scored": 85, "wickets_lost": 2, "target": 180
    })
    assert r.status_code == 200
    assert 0.0 <= r.json()["win_probability"] <= 1.0


def test_predict_unknown_team_is_400_not_500(client):
    """Regression: unfitted team_encoder + blanket except turned 400s into 500s."""
    r = client.post("/predict", json={
        "match_id": 1, "inning": 1,
        "batting_team": "Not A Real Team", "bowling_team": "Chennai Super Kings",
        "overs_completed": 10, "runs_scored": 80, "wickets_lost": 1, "target": None
    })
    assert r.status_code == 400
    assert "Not A Real Team" in r.json()["detail"]


def test_predict_second_innings_requires_target(client):
    r = client.post("/predict", json={
        "match_id": 1, "inning": 2,
        "batting_team": "Mumbai Indians", "bowling_team": "Chennai Super Kings",
        "overs_completed": 10, "runs_scored": 80, "wickets_lost": 1, "target": None
    })
    assert r.status_code == 400


def test_predict_validation_rejects_bad_state(client):
    r = client.post("/predict", json={
        "match_id": 1, "inning": 1,
        "batting_team": "Mumbai Indians", "bowling_team": "Chennai Super Kings",
        "overs_completed": 25,  # > 20 overs: invalid
        "runs_scored": 80, "wickets_lost": 1, "target": None
    })
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /predict/montecarlo (Monte Carlo simulation path)
# ---------------------------------------------------------------------------

def test_montecarlo_second_innings(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 2, "over": 15, "ball": 3,
        "current_runs": 120, "current_wickets": 4, "target": 162,
        "n_simulations": 100
    })
    assert r.status_code == 200
    body = r.json()
    assert body["inning"] == 2
    assert body["win_probability"] is not None
    assert 0.0 <= body["win_probability"] <= 1.0
    assert body["simulations"] == 100


def test_montecarlo_first_innings_returns_score_with_interval(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 1, "over": 10, "ball": 3,
        "current_runs": 85, "current_wickets": 3,
        "n_simulations": 100
    })
    assert r.status_code == 200
    body = r.json()
    assert body["predicted_score"] is not None
    assert body["predicted_score"] >= 85  # cannot predict below current score
    lo, hi = body["confidence_interval"]
    assert lo <= body["predicted_score"] <= hi


def test_montecarlo_uses_database_quality_for_known_player(client):
    """A known high-quality batsman should not lower the win probability."""
    base = {
        "inning": 2, "over": 15, "ball": 3,
        "current_runs": 120, "current_wickets": 4, "target": 162,
        "n_simulations": 150
    }
    quality_lookup = app_module.quality_lookup
    names = list(quality_lookup.keys())
    best = max(names, key=lambda n: quality_lookup[n])
    worst = min(names, key=lambda n: quality_lookup[n])

    r_best = client.post("/predict/montecarlo", json={**base, "striker": {"name": best}})
    r_worst = client.post("/predict/montecarlo", json={**base, "striker": {"name": worst}})
    assert r_best.status_code == 200 and r_worst.status_code == 200
    assert r_best.json()["match_state"]["quality_sources"]["striker"] == f"database:{best}"
    # MC noise: 150 sims -> allow equality band, best should be >= worst - 0.1
    assert r_best.json()["win_probability"] >= r_worst.json()["win_probability"] - 0.1


def test_montecarlo_unknown_player_is_meaningful_400(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 2, "over": 10, "ball": 1,
        "current_runs": 80, "current_wickets": 2, "target": 180,
        "n_simulations": 50,
        "striker": {"name": "Nobody Real"}
    })
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Nobody Real" in detail
    assert "quality" in detail  # tells the caller how to proceed


def test_montecarlo_manual_quality_allows_unknown_player(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 2, "over": 10, "ball": 1,
        "current_runs": 80, "current_wickets": 2, "target": 180,
        "n_simulations": 50,
        "striker": {"name": "Nobody Real", "quality": 8.5}
    })
    assert r.status_code == 200
    assert r.json()["match_state"]["quality_sources"]["striker"] == "explicit"


def test_montecarlo_second_innings_requires_target(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 2, "over": 10, "ball": 1,
        "current_runs": 80, "current_wickets": 2, "n_simulations": 50
    })
    assert r.status_code == 400


def test_montecarlo_rejects_completed_chase(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 2, "over": 18, "ball": 2,
        "current_runs": 165, "current_wickets": 5, "target": 162,
        "n_simulations": 50
    })
    assert r.status_code == 400


def test_montecarlo_invalid_overs_rejected(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 1, "over": 25, "ball": 1,
        "current_runs": 80, "current_wickets": 1, "n_simulations": 50
    })
    assert r.status_code == 422


def test_montecarlo_quality_out_of_range_rejected(client):
    r = client.post("/predict/montecarlo", json={
        "inning": 1, "over": 5, "ball": 1,
        "current_runs": 40, "current_wickets": 0, "n_simulations": 50,
        "striker": {"quality": 15}  # > 10
    })
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Batch endpoint error isolation
# ---------------------------------------------------------------------------

def test_predict_batch_isolates_errors(client):
    r = client.post("/predict_batch", json=[
        {"match_id": 1, "inning": 1, "batting_team": "Mumbai Indians",
         "bowling_team": "Chennai Super Kings", "overs_completed": 10,
         "runs_scored": 80, "wickets_lost": 1, "target": None},
        {"match_id": 2, "inning": 1, "batting_team": "Fake Team",
         "bowling_team": "Chennai Super Kings", "overs_completed": 10,
         "runs_scored": 80, "wickets_lost": 1, "target": None},
    ])
    assert r.status_code == 200
    preds = r.json()["predictions"]
    assert "win_probability" in preds[0]
    assert "error" in preds[1]  # bad team reported, good one unaffected
