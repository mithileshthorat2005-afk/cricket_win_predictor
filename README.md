# Real-Time Cricket Win Probability — Full-Stack System

Ball-by-ball win probability for cricket matches, built as a **two-service
system**: a Python/FastAPI **ML service** that owns all modeling, and a
**Spring Boot orchestrator** that owns match state, idempotent ingestion,
caching, history and real-time push over WebSocket/STOMP. MySQL for durable
state, Redis for caching, Docker Compose to run everything.

> **Honesty note.** Every number and claim below was produced by running the
> code on this machine (tests, an end-to-end script, and a benchmark script).
> The EC2/deploy assets are **prepared and documented** for a single-EC2
> deployment — they have **not** been executed on AWS. See [Deployment](#deployment).

```
client ──► Spring Boot :8080 ──► FastAPI :8000 ──► models (XGBoost / Monte Carlo)
             │  (state, idempotency,          │
             │   cache, history, WS push)     └──► 516-player quality DB
             ├──► MySQL 8  (durable match + prediction state)
             └──► Redis    (per-match-state prediction cache)
```

## Contents

- [Architecture](#architecture)
- [FastAPI ML service](#fastapi-ml-service)
- [Spring Boot orchestrator](#spring-boot-orchestrator)
- [Real-time (WebSocket/STOMP)](#real-time-websocketstomp)
- [Caching & staleness](#caching--staleness)
- [Running with Docker Compose](#running-with-docker-compose)
- [Verification & measured results](#verification--measured-results)
- [Deployment](#deployment)
- [Docs](#docs)

## Architecture

Two services with a single, clear ownership boundary:

| Service | Owns | Does **not** own |
|---|---|---|
| **FastAPI** (`api/app.py`) | Modeling: XGBoost win classifier + Monte Carlo simulation engine; the 516-player batsman-quality DB; model loading (once, at startup) | Match state, persistence, clients |
| **Spring Boot** (`backend/`) | Match state, idempotent ball ingestion, prediction history + staleness, caching, WebSocket push | Any model — it calls FastAPI |

The FastAPI service is the **only** owner of ML. Spring Boot never reimplements
a model; it calls FastAPI over HTTP and is a faithful client of the contracts in
[`README.api.md`](README.api.md).

## FastAPI ML service

Two prediction paths, both real:

- **`POST /predict`** — fast XGBoost win classifier. (Backward-compatible with
  the original project; some match-context features are zero-filled on this
  path — see [`AUDIT.md`](AUDIT.md) limitation #5.)
- **`POST /predict/montecarlo`** — the Monte Carlo simulation engine
  (`src/win_probability_engine.py`), ball-by-ball, driven by a Random-Forest
  `predict_proba`, with striker/non-striker quality adjustment, strike rotation
  and phase logic. **Innings 2** returns a win probability for the chase;
  **innings 1** returns a predicted final score with a 10th–90th percentile
  interval.

Also `GET /health` (reports which models are loaded), `GET /teams` (15 IPL
teams), `GET /players?search=` (search the 516-player DB), `GET /features`,
and `POST /predict_batch` (per-item error isolation).

Models are loaded **once at startup** (lifespan handler); requests never trigger
a reload. Full request/response schemas: [`README.api.md`](README.api.md).

## Spring Boot orchestrator

Layered (`controller` / `service` / `repository` / `client` / `config`), backed
by MySQL. Key behaviors, all covered by tests:

- **Idempotent ingestion.** `POST /api/matches/{id}/balls` accepts a ball event
  with an `eventId` (derived from match/inning/over/ball if omitted). A repeated
  event is stored once and flagged `duplicate: true` — replayed feeds can't
  double-count runs.
- **Match state + versioning.** Every accepted ball advances a `stateVersion`.
  Innings transitions (including **all-out**) materialize the next innings
  state with the correct chase target.
- **Prediction history.** Predictions are stored with the `stateVersion` they
  were computed from and are **stale-flagged** when the live version has moved
  on (see below).
- **Graceful ML failure.** If FastAPI is down, ball ingestion still succeeds;
  the response carries `predictionError` and `prediction: null`. A direct
  `POST /predict` returns **503**. The service never invents a probability.

## Real-time (WebSocket/STOMP)

`/ws` (with SockJS fallback) publishes structured JSON to per-match topics:

| Topic | Payload |
|---|---|
| `/topic/match/{id}/prob` | `{matchId, inning, winProbability, predictedScore, modelType, stateVersion, latencyMs}` |
| `/topic/match/{id}/score` | `{matchId, inning, battingTeam, runs, wickets, oversCompleted, stateVersion}` |
| `/topic/match/{id}/ball`  | `{matchId, eventId, inning, over, ball, striker, bowler, runs, wicket, stateVersion}` |

A demo client is in `backend/src/main/resources/static/index.html`; a STOMP
integration test asserts the round-trip.

## Caching & staleness

Predictions are cached in Redis keyed by **all prediction-relevant match
state** (innings, runs, wickets, balls, target, model, sims). The cache is
invalidated when a new ball advances the state, so a cached value is never
served for a changed state. Failures are **never cached**. A prediction
computed from an older `stateVersion` is flagged `stale: true` in history and
is not published as current.

## Running with Docker Compose

Four services: `mysql`, `redis`, `fastapi`, `backend`.

```bash
docker compose up --build
# backend    → http://localhost:8080  (actuator/health)
# fastapi    → http://localhost:8000  (docs, /health)
```

**Host ports are overridable** — useful when something on the host already
owns 3306/6379/8080 (this machine runs a local MySQL and an Oracle listener):

```bash
MYSQL_HOST_PORT=3307 REDIS_HOST_PORT=6380 BACKEND_HOST_PORT=8081 docker compose up --build
```

Defaults and the prediction-tuning env vars are documented in
[`.env.example`](.env.example). See [`docs/`](docs/) for a fuller compose guide.

## Verification & measured results

All results below were produced by running the code on this machine.

| Check | Result | How |
|---|---|---|
| Spring Boot tests | **52/52 pass** | `mvn test` |
| FastAPI tests | **20/20 pass** | `api/tests/test_api.py` |
| End-to-end (live stack) | **19/19 checks pass** | `verify-e2e.ps1` |
| Monte Carlo round-trip | **1333 ms** (300 sims) via Spring Boot | e2e `[5]` |
| Duplicate event idempotency | runs **not** double-counted | e2e `[4]` |
| FastAPI-down resilience | ingest survives; predict → 503; **no fabricated probability** | e2e `[7]` |
| Players in quality DB | **516** | verified |

The end-to-end script (`verify-e2e.ps1`) drives the whole stack against the
running Docker containers: creates a match, fast-forwards innings 1 to open a
chase, verifies duplicate-event idempotency, runs a real Monte Carlo
prediction, confirms staleness flags, and stops the FastAPI container mid-flight
to prove ingestion survives an ML outage without inventing numbers.

**Monte Carlo performance** (`benchmark-mc.ps1`, real measurements — median of
runs, 2nd-innings chase path):

| Simulations | Median latency |
|---|---|
| 300 | ~4.7 s (1.3 s via Spring's fast path) |
| 500 (API default) | ~3.1 s |
| 1000 | ~14.7 s |

The **1st-innings score path** is markedly slower and more variable (measured
22–539 s, no early exit). This is a documented limitation, handled honestly:
the orchestrator returns **503** for a slow/down ML call rather than a fabricated
probability, and the e2e script drives the fast chase path.

## Deployment

Dockerized for **single-EC2 deployment**. `deploy/` contains a production
compose file, `ec2-setup.sh`, and a README. These are **prepared and documented
but have not been run on AWS** — the honest claim is "dockerized and scripted
for a single EC2 instance," not "deployed to AWS." See [`deploy/README.md`](deploy/README.md).

## Docs

| Doc | What it covers |
|---|---|
| [`AUDIT.md`](AUDIT.md) | Pre-existing defects found in the original project (verified by execution) and how each was fixed |
| [`README.api.md`](README.api.md) | Full, verified API contracts for both services + WebSocket topics |
| [`deploy/README.md`](deploy/README.md) | Deployment notes (scripts only) |
