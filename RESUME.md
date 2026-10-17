# Resume Blurb — Real-Time Cricket Win Probability

Short (4–5 line) version, for a resume "Projects" bullet:

> **Real-Time Cricket Win Probability (Full-Stack)**
> Two-service system: a FastAPI ML service (XGBoost win classifier + Monte Carlo
> simulation engine, 516-player batsman-quality DB, models loaded once at startup)
> and a Spring Boot orchestrator with MySQL + Redis. Built idempotent ball-event
> ingestion (event IDs, no double-counted runs), versioned prediction history with
> stale-result protection, and real-time probability push over WebSocket/STOMP.
> Verified end-to-end with 52 Spring Boot tests (52/52), 20 FastAPI tests (20/20),
> and a 19/19 live-stack e2e run covering duplicate events and ML-service failure
> (ingestion survives an ML outage with no fabricated probability). Dockerized via
> Docker Compose for single-EC2 deployment.

---

## Longer version (for a cover letter / interview talking points)

I built a full-stack, real-time cricket win-probability system that keeps the
existing ML work and adds a production-shaped backend around it.

**ML (FastAPI, the only owner of modeling).** Two real prediction paths: a fast
XGBoost win classifier and a Monte Carlo simulation engine that simulates the
game ball-by-ball off Random-Forest probabilities, adjusting for striker /
non-striker quality. It ships a 516-player batsman-quality database. Models load
once at startup. I audited the original project first and fixed real defects by
execution — an unfitted team encoder that crashed `/predict`, a duplicated
`inning.1` feature column that broke every request, and 500-instead-of-400 error
handling.

**Backend (Spring Boot + MySQL + Redis).** Layered architecture owning match
state, caching and history. Ball ingestion is idempotent via event IDs, so a
replayed feed can't double-count runs. Every accepted ball advances a
`stateVersion`; predictions are cached in Redis keyed on all prediction-relevant
state, invalidated on new balls, and failures are never cached. Prediction
history is versioned and stale-flagged so an out-of-date probability is never
presented as current.

**Real-time (WebSocket/STOMP).** Structured JSON published to per-match topics
(`/topic/match/{id}/prob`), with a demo client and an integration test.

**Verification (no unverified claims).** 52/52 Spring tests, 20/20 FastAPI
tests, and a 19/19 live end-to-end run against the running Docker stack —
covering duplicate-event idempotency and an ML-service outage (ingestion
survives; predict returns 503; the system never invents a probability). Monte
Carlo round-trip measured at ~1.3 s (300 sims) through Spring Boot.

**Honest scoping.** The slow first-innings Monte Carlo path (measured 22–539 s)
is handled as a 503, not masked. Everything is Dockerized via Compose for a
single-EC2 deployment; the deploy scripts are prepared and documented but were
not executed on AWS.

---

## Claim-to-evidence table

Every claim above maps to something runnable in the repo:

| Claim | Evidence |
|---|---|
| 516-player quality DB | `models/batsman_quality.pkl`, `GET /players` |
| Monte Carlo engine is real (ball-by-ball) | `src/win_probability_engine.py` |
| Models load once at startup | FastAPI lifespan handler in `api/app.py` |
| 52/52 Spring tests | `cd backend && mvn test` |
| 20/20 FastAPI tests | `api/tests/test_api.py` |
| 19/19 e2e (dup events + ML-down) | `verify-e2e.ps1` |
| MC ~1.3 s (300 sims) via Spring | `verify-e2e.ps1` section [5] |
| Idempotent ingestion / no double count | `verify-e2e.ps1` section [4] |
| No fabricated probability when ML down | `verify-e2e.ps1` section [7] |
| Stale-result protection (versioned history) | `verify-e2e.ps1` section [6] |
| 1st-innings MC slowness 22–539 s | `benchmark-mc.ps1` + e2e notes |
| Single-EC2 (not run on AWS) | `deploy/README.md` |

## Do NOT claim

- "Deployed to AWS / running on EC2" — the scripts are prepared, not executed.
- Any cache hit-rate or throughput % — not measured with a real Redis benchmark.
