# Architecture

This document describes the **implemented** architecture of the real-time
cricket win-probability system. Every element below exists in the code and is
covered by tests — it is a description of what is built, not a design proposal.

---

## 1. The problem this system solves

Given a live, ball-by-ball cricket feed, answer two questions continuously:

1. **Who is winning right now?** (win probability for the batting side)
2. **How is that answer changing as each ball is bowled?**

…while guaranteeing that:

- a **replayed / duplicated ball** is never counted twice (idempotency),
- a **stale answer** computed from an older match state is never shown as if it
  were current (stale-result protection),
- a **slow or down ML service** never blocks ball ingestion and never causes a
  fabricated probability to be published (graceful degradation).

---

## 2. Two services, one ownership boundary

The system is deliberately split into two services with a crisp boundary:

| | **ML service (FastAPI, Python)** | **Orchestrator (Spring Boot, Java)** |
|---|---|---|
| Port | 8000 | 8080 (8081 on this dev host) |
| Owns | Modeling, the 516-player quality DB, model lifecycle | Match state, persistence, idempotency, caching, history, real-time push, clients |
| Does **not** own | Match state, persistence, any client-facing state | Any model — it calls FastAPI over HTTP |

The FastAPI service is the **only** owner of ML. The orchestrator never
re-implements a model; it is a faithful client of the contracts in
[`README.api.md`](../README.api.md). This means the existing, working ML code was
**preserved, not rewritten** — a hard requirement of this project.

```
                        ┌──────────────────────────────────────────────┐
   ball feed ─────────► │  Spring Boot orchestrator  :8080             │
   (idempotent          │                                              │
    eventId)            │  controller ─► MatchService ─► MySQL         │
                        │      │              (transactional,          │
                        │      │               idempotent)             │
                        │      │                                       │
                        │      ├─► WebSocketPublisher ─► STOMP topics  │
                        │      │        (publish AFTER commit,         │
                        │      │         stale-guarded by version)     │
                        │      │                                       │
                        │      └─► PredictionService ─► MatchCache(Redis)
                        │                │                             │
                        └────────────────┼─────────────────────────────┘
                                         │ HTTP (WebClient)
                                         ▼
                        ┌──────────────────────────────────────────────┐
                        │  FastAPI ML service  :8000                   │
                        │                                              │
                        │  /predict           ► XGBoost classifier     │
                        │  /predict/montecarlo ► Monte Carlo engine     │
                        │                        + 516-player DB        │
                        │  models loaded ONCE at startup               │
                        └──────────────────────────────────────────────┘
```

---

## 3. Data model (MySQL, Flyway `V1__init.sql`)

Four tables, created automatically on first boot by Flyway. Portable across
MySQL 8 (prod) and H2-in-MySQL-mode (tests).

```
matches  1───*  innings  1───*  deliveries
   │
   └───────────*  predictions
```

- **`matches`** — `team1`, `team2`, `status` (LIVE/COMPLETED),
  `current_innings`, and **`state_version`**: a monotonically increasing
  counter bumped on **every accepted ball**. This integer is the backbone of
  the entire staleness model.
- **`innings`** — per-innings totals (`runs`, `wickets`, `balls_bowled`),
  the `target` (innings 2 only), and a `completed` flag. Unique on
  `(match_id, inning_number)`.
- **`deliveries`** — every accepted ball. Carries the idempotency key
  **`UNIQUE (match_id, event_id)`**, the ball detail (over/ball/striker/
  bowler/runs/wicket) and `state_version_after`.
- **`predictions`** — every computed prediction, tagged with the
  **`state_version`** it was computed from, the `model_type`, the result
  (`win_probability` XOR `predicted_score`) and the measured `latency_ms`.

Key design choice: `over` is a **reserved word** in MySQL 8 (window functions),
so the column is named `over_number`.

---

## 4. Ingestion: idempotency and innings transitions

`MatchService.ingestBall` runs in a **single transaction** — the delivery row,
innings totals and match version commit together or not at all.

```
POST /api/matches/{id}/balls   { eventId, inning, over, ball, striker, bowler, runs, wicket }
  │
  ├─ match already COMPLETED?            → 400 InvalidMatchState
  ├─ (match_id, event_id) already stored?→ return current state, duplicate=true   ← IDEMPOTENCY
  ├─ resolve target innings (open 2nd if 1st just ended)
  ├─ apply ball: runs += , balls_bowled++, wickets++ (if wicket)
  ├─ innings over?  (all-out ≥10 wickets | ≥120 balls | chased down)
  │     ├─ innings 1 over → open innings 2, target = innings1_total + 1
  │     └─ innings 2 over → match COMPLETED
  ├─ match.state_version++
  ├─ evict cached state (Redis)          ← BEFORE commit
  └─ save delivery + innings + match     ← COMMIT
```

**Idempotency** rests on the database unique constraint, not on an in-memory
check — so two concurrent submissions of the same `eventId` cannot both commit;
one wins, the other is a duplicate. The event ID defaults to
`m{matchId}:i{inning}:o{over}:b{ball}` when the client omits it.

**The all-out edge case** (a real bug this project fixed): when the 10th wicket
falls, the match transitions to innings 2. An earlier version flipped
`current_innings` without creating the innings-2 row, so the post-commit
`getState()` threw *"No state yet"* and a successfully-committed ball returned
HTTP 400. The fix **materialises the innings-2 row** (with `target = total + 1`)
at transition time, so the current innings always exists. Verified by
`verify-e2e.ps1` section [3].

---

## 5. Prediction pipeline: caching and staleness

`PredictionService.predict` is where the two interesting guarantees are
enforced.

### 5.1 Stale-result protection

The `state_version` is snapshotted **before** the (possibly slow) ML call:

```java
long versionAtRequest = match.getStateVersion();   // snapshot first
// ... slow FastAPI call ...
new Prediction(matchId, inning, versionAtRequest, model, ...);
```

The stored prediction therefore **remembers exactly which match state it
describes**. Two independent guards use it:

- **At read time** — a prediction whose `state_version < live_version` is
  returned with `"stale": true` (`MatchService.toPredictionResponse`).
- **At publish time** — `WebSocketPublisher.publishProbability` tracks the last
  published version per match and **drops** any probability computed from an
  older version, so a slow Monte Carlo result can never overwrite a newer one
  on the live topic.

### 5.2 Redis cache (`MatchCache`)

Two kinds of key:

| Key | Contents | Invalidation |
|---|---|---|
| `match:state:{matchId}` | Latest `MatchStateResponse` JSON | Evicted inside the ingestion transaction, before commit |
| `match:pred:{matchId}:v{version}:{model}:{sims}:{team}[:s…][:n…]` | A prediction result | Key includes **every** prediction-relevant dimension |

Because the prediction key embeds `stateVersion` (bumped per ball), model,
simulation count and batsman context, **two different match states can never
collide on the same cached prediction** — correctness does not depend on an
explicit invalidation call.

**Failure policy:** every Redis operation is wrapped; an error is logged once
per JVM and treated as a cache miss / skipped write. The cache is a pure
optimisation — a prediction **failure is never cached** (failures throw before
`putPrediction` is reached).

### 5.3 Graceful ML degradation

- Ball ingestion **never fails because ML is down.** The controller catches the
  ML exception, sets `predictionError`, leaves `prediction: null`, and still
  returns the accepted ball.
- An explicit `POST /{id}/predict` against a dead ML returns **503**.
- A first-innings Monte Carlo returns a **score with a percentile interval**,
  `win_probability = null` — never a fabricated `0.0`.

---

## 6. Real-time layer (WebSocket / STOMP)

`WebSocketConfig` registers a STOMP endpoint at `/ws` (with SockJS fallback) and
enables a simple broker. `WebSocketPublisher` sends to per-match topics
**after** the ingestion transaction commits (a failed ingestion is never
broadcast):

| Topic | Payload | Sent when |
|---|---|---|
| `/topic/match/{id}/score` | `{matchId, inning, battingTeam, runs, wickets, oversCompleted, stateVersion}` | every accepted ball |
| `/topic/match/{id}/ball` | `{matchId, eventId, inning, over, ball, striker, bowler, runs, wicket, stateVersion}` | every accepted ball |
| `/topic/match/{id}/prob` | `{matchId, inning, winProbability, predictedScore, modelType, stateVersion, latencyMs}` | every prediction (stale-guarded) |

A browser demo client is served at `/index.html`. The round-trip is asserted by
`StompIntegrationTest`.

---

## 7. ML service internals (FastAPI)

- **Two real prediction paths**, both preserved from the original project:
  - `POST /predict` — fast **XGBoost** win classifier (`best_xgboost_model`).
  - `POST /predict/montecarlo` — the **Monte Carlo engine**
    (`src/win_probability_engine.py`), which simulates the game ball-by-ball
    using a Random-Forest `predict_proba`, adjusting for striker/non-striker
    quality and strike rotation. Innings 2 → win probability; innings 1 →
    predicted final score with a 10th–90th percentile interval.
- **Models load once at startup** (lifespan handler). Requests never trigger a
  reload — a hard requirement.
- **516-player batsman-quality database** (`batsman_quality.pkl`) adjusts the
  simulation by player. Known players are looked up; unknown players require an
  explicit quality or get a descriptive 400.
- **Backward compatibility:** the original `/predict` contract was kept intact
  (including its zero-filled context features — a documented limitation), and a
  separate, richer `/predict/montecarlo` path was **added** rather than
  replacing it.

### Pre-existing defects fixed during the audit

The FastAPI service was audited against its own (stale) claims and several real,
execution-verified defects were fixed — see [`AUDIT.md`](../AUDIT.md). Notably:
an unfitted team encoder that crashed `/predict`, a duplicated `inning.1`
feature column that broke every request, and blanket `except` blocks that turned
400s into 500s.

---

## 8. Request lifecycle: one ball, end to end

```
client                Spring Boot                    FastAPI            MySQL   Redis   WS clients
  │  POST /balls         │                             │                  │       │          │
  │─────────────────────►│                             │                  │       │          │
  │                      │ ingestBall (tx)             │                  │       │          │
  │                      │── idempotency check ────────┼──────────────────┼──────►│          │
  │                      │── apply ball, version++ ────┼──────────────────┼──────►│          │
  │                      │── evict state ──────────────┼──────────────────┼──────►│          │
  │                      │   COMMIT                    │                  │       │          │
  │                      │                             │                  │       │          │
  │                      │ publish score + ball ───────┼──────────────────┼───────┼─────────►│
  │                      │                             │                  │       │          │
  │                      │ predict (snapshot version)  │                  │       │          │
  │                      │── cache lookup ─────────────┼──────────────────┼──────►│          │
  │                      │   (miss)                    │                  │       │          │
  │                      │── POST /predict ───────────►│ simulate         │       │          │
  │                      │◄────────────────────────────│                  │       │          │
  │                      │── save prediction ──────────┼──────────────────┼──────►│          │
  │                      │── cache write ──────────────┼──────────────────┼──────►│          │
  │                      │ publish probability ────────┼──────────────────┼───────┼─────────►│
  │◄─────────────────────│  (state + prediction)       │                  │       │          │
```

On a subsequent identical request at the same `stateVersion`, step "cache
lookup" **hits** and the whole FastAPI round-trip is skipped.

---

## 9. Configuration

Spring Boot reads sensible defaults from `application.properties` and overrides
from environment (see [`docker-compose.yml`](../docker-compose.yml) and
[`.env.example`](../.env.example)). Notables:

| Property | Purpose |
|---|---|
| `cricket.fastapi.base-url` | ML service location (default `http://localhost:8000`) |
| `cricket.fastapi.health-timeout-ms` | Readiness timeout (2000 ms prod / 15000 ms test) |
| `cricket.prediction.auto-on-ball` | Predict on every accepted ball (compose default `true`) |
| `cricket.prediction.mc-simulations` | Default Monte Carlo simulation count (300) |

Host ports are overridable (`MYSQL_HOST_PORT`, `REDIS_HOST_PORT`,
`BACKEND_HOST_PORT`) because a dev machine may already own 3306/6379/8080.
