# API Contracts

This document describes the **actual implemented contracts** (verified by tests), not aspirations.

## 1. FastAPI ML service (`api/app.py`, port 8000)

### `POST /predict` — XGBoost win probability (fast path)

Request (pydantic `MatchState`):

```json
{
  "match_id": 1,
  "inning": 2,
  "batting_team": "Mumbai Indians",       // must be one of the 15 known teams
  "bowling_team": "Chennai Super Kings",
  "overs_completed": 10.2,                 // cricket decimal: 10.2 = 10 overs + 2 balls
  "runs_scored": 85,
  "wickets_lost": 2,                       // 0..10
  "target": 180                            // required for inning=2, null otherwise
}
```

Response (200):

```json
{
  "win_probability": 0.421,
  "batting_team": "Mumbai Indians",
  "bowling_team": "Chennai Super Kings",
  "inning": 2,
  "match_state": { "...": "echo of the request" },
  "confidence": "Low",                     // High | Medium | Low
  "key_factors": ["⚡ High required run rate"]
}
```

Errors: `400` unknown team / missing target (with `detail`), `422` schema violation, `500` model failure.
Note: many match-context features are zero-filled on this path (see limitations).

### `POST /predict/montecarlo` — Monte Carlo simulation (rich path)

Request (pydantic `MonteCarloRequest`):

```json
{
  "match_id": 1,
  "inning": 2,
  "over": 15,                              // integer overs completed
  "ball": 3,                               // ball within over, 1..6
  "current_runs": 120,
  "current_wickets": 4,
  "target": 162,                           // required for inning=2
  "n_simulations": 500,                    // 50..5000
  "striker":     {"name": "V Kohli", "quality": null, "runs": 40, "balls": 30},
  "non_striker": {"name": "MS Dhoni", "quality": null, "runs": 20, "balls": 15}
}
```

- `name` must exist in the 516-player quality database, **or** an explicit `quality` (1–10) must be supplied for unknown players (`400` otherwise, with a descriptive message).
- `striker`/`non_striker` optional; defaults are quality 7 (striker) / 5 (non-striker).
- `balls_remaining` derived from `over`/`ball` when omitted.

Response (200), inning 2 (chase):

```json
{
  "inning": 2,
  "win_probability": 0.7142,               // batting team's chance to win
  "predicted_score": null,
  "confidence_interval": null,
  "simulations": 500,
  "match_state": {"...": "state echo", "quality_sources": {"striker": "database:V Kohli", "non_striker": "default"}},
  "note": "Probability that the batting team wins the chase."
}
```

Response (200), inning 1 (first innings → **score, not probability**):

```json
{
  "inning": 1,
  "win_probability": null,
  "predicted_score": 158.4,
  "confidence_interval": [130.0, 187.0],   // 10th–90th percentile
  "simulations": 500,
  "match_state": {"...": "state echo"},
  "note": "Final-score prediction ... (10th-90th percentile interval)."
}
```

Errors: `400` (missing target, completed chase, unknown player without quality, unknown team), `422` schema violation, `500` simulation failure.

### Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | `{"status","model_loaded","scaler_loaded","mc_engine_loaded","players_loaded"}` |
| `GET /teams` | 15 IPL teams known to the model |
| `GET /players?search=&limit=` | Search the 516-player quality database |
| `GET /features?top_n=` | Top model features (normalized gain) |
| `POST /predict_batch` | Batch of `MatchState`; per-item errors isolated |

## 2. Spring Boot orchestrator (`backend/`, port 8080)

### REST API (`/api/matches`)

| Method & path | Purpose | Responses |
|---|---|---|
| `POST /api/matches` | Create a demo match (`{"team1","team2"}`) | 201, 400 validation |
| `GET /api/matches/live` | List LIVE matches | 200 |
| `GET /api/matches/{id}` | Match details | 200, 404 |
| `GET /api/matches/{id}/state` | Current innings state + `stateVersion` | 200, 404 |
| `POST /api/matches/{id}/balls` | Ingest a ball event (idempotent) | 200 (duplicate flag), 400 invalid state |
| `POST /api/matches/{id}/predict` | Request prediction, optional body `{"model","nSimulations","strikerName","strikerQuality","nonStrikerName","nonStrikerQuality"}` | 200, 404, 400, 503 if ML down |
| `GET /api/matches/{id}/predictions` | Prediction history (stale-flagged) | 200 |
| `POST /score` | Legacy endpoint from the original livecricket project | 200 |

Ball event:

```json
{
  "eventId": "m1:i2:o15:b3",   // optional idempotency key; derived from match/inning/over/ball when omitted
  "inning": 2,
  "over": 15, "ball": 3,
  "striker": "Player X", "nonStriker": "Player Y", "bowler": "Bowler Z",
  "runs": 4, "wicket": false
}
```

Ingest response:

```json
{
  "duplicate": false,
  "matchId": 1,
  "state": { "matchId":1, "inning":2, "battingTeam":"Team B", "oversCompleted":15.3,
             "runs":124, "wickets":4, "ballsBowled":93, "ballsRemaining":27,
             "target":171, "stateVersion":12 },
  "prediction": { "id":7, "inning":2, "stateVersion":12, "modelType":"xgboost",
                  "winProbability":0.631, "predictedScore":null,
                  "latencyMs":41, "createdAt":"...", "stale":false },
  "predictionError": null      // populated (with prediction=null) when the ML call fails
}
```

### WebSocket/STOMP (`/ws`, SockJS fallback)

| Topic | Payload |
|---|---|
| `/topic/match/{id}/score` | `{"matchId","inning","battingTeam","runs","wickets","oversCompleted","stateVersion"}` |
| `/topic/match/{id}/prob` | `{"matchId","inning","winProbability","predictedScore","modelType","stateVersion","latencyMs"}` |
| `/topic/match/{id}/ball` | `{"matchId","eventId","inning","over","ball","striker","bowler","runs","wicket","stateVersion"}` |
| `/topic/live` | Legacy livecricket payload `{"score":{...},"commentary":null\|"..."}` |

Stale-result protection: `stateVersion` increments per accepted ball; a probability
computed from an older version is never published (and is flagged `"stale": true`
in history queries).

### Spring Boot → FastAPI mapping

| Spring | FastAPI |
|---|---|
| `FastApiXgbRequest` | `MatchState` (`/predict`) |
| `FastApiXgbResponse` | `PredictionResponse` |
| `FastApiMcRequest` | `MonteCarloRequest` (`/predict/montecarlo`) |
| `FastApiMcResponse` | `MonteCarloResponse` |
| error body `{"detail"}` | mapped to HTTP 503 with FastAPI's detail message |

Base URL is configurable: `FASTAPI_BASE_URL` (default `http://localhost:8000`).
