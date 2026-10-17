# Audit Report — Original Project (before the full-stack upgrade)

Audited: 2026-10-15. All findings verified against actual source code, artifacts
and test runs — not against the (stale) README.

## 1. What existed

### Data
| Asset | Detail |
|---|---|
| `data/raw/deliveries.csv` | IPL ball-by-ball data, ~179K deliveries |
| `data/processed/*.csv` | 6 derived datasets (23–46 MB each) |
| `data/processed/match_summary.csv` | 754 matches, 15 IPL franchises |

### ML artifacts (`models/`)
| Model | Type | Notes |
|---|---|---|
| `best_xgboost_model.pkl`/`.json` | XGBoost win classifier | JSON = portable re-save via `save_model_json.py` |
| `first_innings/lightgbm_model.pkl` | LightGBM regressor | Final-score prediction |
| `ball_outcome/random_forest_model.pkl` | Random Forest, 7 classes | Powers the Monte Carlo engine (~24 MB) |
| `batsman_quality.pkl` | Lookup dict, **exactly 516 players** | Built by `scripts/build_batsman_quality.py` |
| `scaler.pkl`, `feature_columns.pkl`, `team_encoder.pkl` | Preprocessors | 30 feature columns incl. a duplicate `inning.1` |

### Prediction engines
1. **`src/win_probability_engine.py` — Monte Carlo simulation** (the project's
   crown jewel): ball-by-ball simulation using the RF `predict_proba`, striker/
   non-striker quality & strike-rate adjustment, strike rotation, phase logic,
   `@lru_cache` on ball-outcome lookups. Two modes: first-innings score with
   percentile intervals; second-innings chase win probability.
2. **`api/app.py` — FastAPI service**: `/predict` (XGBoost classifier),
   `/predict_batch`, `/health`, `/teams`, `/features`; models loaded once at
   startup.
3. **`app.py` — Streamlit UI**: uses the Monte Carlo engine + 516-player DB.

## 2. Pre-existing defects found (all verified by execution)

| # | Defect | Evidence | Status in this upgrade |
|---|---|---|---|
| 1 | `team_encoder.pkl` saved **unfitted** — `/predict` and `/teams` crashed with `AttributeEncoder has no attribute 'classes_'` | Loaded artifact directly | ✅ Fixed: refitted on the 15 real teams; `win_predictor.py` fixed so retraining can't regress |
| 2 | `/predict` always failed with `['inning.1'] not in index` — `feature_columns.pkl` contains a duplicate `inning.1` column (CSV round-trip) never supplied by the API | Loaded `feature_columns.pkl`; reproduced 500 | ✅ Fixed: API now supplies `inning.1` with the same value as `inning` (matches training data) |
| 3 | Unknown-team validation returned **500 instead of 400** — blanket `except Exception` caught `HTTPException` | Code path tracing + test | ✅ Fixed (`except HTTPException: raise` first) |
| 4 | `/features` crashed — `xgb.Booster` has no `feature_importances_` | Endpoint call | ✅ Fixed via `get_score(importance_type='gain')`, normalized |
| 5 | FastAPI `/predict` did **not** use the Monte Carlo engine; ~15 match-context features hardcoded to 0 | Source | ⚠️ Preserved as-is (backward compat); a real MC path was **added** as `/predict/montecarlo` |
| 6 | No automated tests at all | Repo scan | ✅ 20 API tests added (FastAPI), 4 test classes (Spring Boot) |
| 7 | README described "Day 1" status only | Read | ✅ Rewritten (root `README.md` now documents the verified full-stack system) |

## 3. Architecture before the upgrade

```
Streamlit UI ───────────► WinProbabilityEngine (Monte Carlo + 516-player DB)
FastAPI /predict ───────► XGBoost classifier (zero-filled context features)
No database, no cache, no WebSocket pipeline, no match state management,
no idempotent event ingestion, no Java backend.
```

Deployment: a Dockerfile for the FastAPI service existed. **No
docker-compose, no deployment scripts, and no AWS/EC2 configuration existed in
the repository** — the EC2 claim could not be substantiated from code.

## 4. Verified genuine claims

- 516-player batsman database — ✅ exactly 516 entries
- Monte Carlo simulation engine — ✅ real, ball-by-ball, RF-probability-driven
- Cricket-specific features (required run rate, pressure, phase, resources,
  momentum) — ✅ present in `src/advanced_features.py` and the engine
- Caching/optimization mechanism — ✅ `lru_cache` in the simulation engine
- Models loaded once at startup — ✅ FastAPI lifespan/startup handler
- AWS EC2 deployment — ⚠️ **unverifiable from the repository**

## 5. Environment notes (verified)

- Python venv is 3.14 with newer libs than `requirements.txt` pins
  (xgboost 3.2 vs 1.7.6, fastapi 0.143 vs 0.104) — Docker alignment handled
  in the Dockerfile phase.
- Machine has Java 24, Maven 3.9.16, Docker 29 + Compose v5; no local MySQL
  client (MySQL runs in Docker).
- JDK 23+ disables implicit annotation processing — Lombok requires explicit
  `annotationProcessorPaths` (configured in `backend/pom.xml`).
