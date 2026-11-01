# Running the Stack

Everything runs via **Docker Compose** — four services, no manual database or
model setup. This guide covers a cold start on a development machine and the
day-to-day operations.

## Prerequisites

- **Docker Desktop** running (WSL 2 backend). Start it and give the engine ~20 s.
- Nothing else. MySQL schema is created by **Flyway** on first boot and the ML
  models are **baked into the FastAPI image**.

## Port note (important on a shared dev machine)

The compose file defaults to the conventional ports — MySQL `3306`, Redis
`6379`, backend `8080`. On a typical Windows dev box a **MySQL80 Windows service
already owns 3306** and an **Oracle TNS Listener often owns 8080**. The compose
file therefore makes all three host ports overridable:

| Variable | Default | This machine |
|---|---|---|
| `MYSQL_HOST_PORT` | 3306 | **3307** |
| `REDIS_HOST_PORT` | 6379 | 6379 |
| `BACKEND_HOST_PORT` | 8080 | **8081** |

Set them **once** in a `.env` file so you never type them again:

```powershell
cd "E:\CRICKET MODEL"
Copy-Item .env.example .env     # already sets 3307 / 8081
```

`.env` is git-ignored, so credentials are never committed.

## Cold start

```powershell
cd "E:\CRICKET MODEL"
docker compose up -d --build
```

- `--build` builds both images (FastAPI with models baked in; backend with the
  Spring Boot JAR). First run takes a few minutes; later starts are quick.
- `-d` runs detached.

What happens automatically:

1. **MySQL** boots → **Flyway** (`V1__init.sql`) creates the `cricket` schema.
2. **FastAPI** loads XGBoost, the Random-Forest ball-outcome model and the
   516-player DB **once at startup**.
3. **Backend** waits for MySQL to be healthy, connects, then serves the API.

Wait ~30–60 s and confirm all four are healthy:

```powershell
docker compose ps
# backend, fastapi, mysql, redis  ->  all "(healthy)"
```

## Verify it works

```powershell
curl http://localhost:8081/actuator/health   # backend -> {"status":"UP"}
curl http://localhost:8000/health            # fastapi -> models loaded

# full end-to-end test against the live stack
$env:E2E_API="http://localhost:8081"; $env:E2E_ML="http://localhost:8000"
$env:E2E_COMPOSE_DIR="E:\CRICKET MODEL"
.\verify-e2e.ps1
```

`verify-e2e.ps1` drives the whole pipeline: create a match → fast-forward
innings 1 to open a chase → assert duplicate-event idempotency → run a real
Monte Carlo prediction → confirm staleness flagging → **stop the FastAPI
container** to prove ingestion survives an ML outage without inventing numbers.

## Using the system

- **REST** — see [`README.api.md`](../README.api.md) for exact payloads:
  `POST /api/matches`, `POST /api/matches/{id}/balls`,
  `POST /api/matches/{id}/predict`, `GET /api/matches/{id}/predictions`.
- **WebSocket / STOMP** — connect to `ws://localhost:8081/ws`, subscribe to
  `/topic/match/{id}/prob`. Browser demo at `http://localhost:8081/index.html` —
  it loads the match's current state the moment you subscribe, and has
  **+ New match** / **▶ Bowl next ball** buttons so you can drive a full match
  from the browser with no terminal commands.
- **FastAPI directly** — interactive docs at `http://localhost:8000/docs`.

## Operations

```powershell
docker compose down          # stop + remove containers (KEEPS the MySQL volume)
docker compose down -v       # stop AND wipe the database (clean slate)
docker compose logs -f backend   # tail backend logs
docker compose logs -f fastapi   # tail ML logs
docker compose restart backend   # restart one service
```

Match data persists in the `mysql-data` volume across `down`/`up`, so it
survives restarts unless you use `-v`.

## Tuning predictions

Set in `.env` (read by compose into the backend container):

| Variable | Default | Meaning |
|---|---|---|
| `PREDICTION_DEFAULT_MODEL` | `xgboost` | Model used when a request doesn't specify one |
| `PREDICTION_MC_SIMULATIONS` | `300` | Default Monte Carlo simulation count |
| `PREDICTION_AUTO_ON_BALL` | `true` | Predict on every accepted ball (`false` = faster ingestion, no per-ball prediction) |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `port is already allocated` on 3306/8080 | `.env` missing or wrong. Re-copy `.env.example`, `docker compose down`, `up -d`. |
| Backend never becomes healthy | `docker compose logs backend`. If MySQL was slow to accept connections, the backend retries — give it a minute. |
| Containers die randomly / WSL thrash | Memory pressure on a small host. The WSL VM is capped via `C:\Users\ASUS\.wslconfig` (3 GB + swap). `wsl --shutdown`, restart Docker Desktop, `docker compose up -d`. |
| 503 from `/predict` | FastAPI is down or slow — this is **by design**: the orchestrator returns 503 rather than fabricating a probability. Check `docker compose ps fastapi`. |
