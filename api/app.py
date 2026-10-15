from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd
import xgboost as xgb
import numpy as np
import joblib
import uvicorn
from typing import Optional, List, Dict
import os
import sys
import threading

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import your feature engineering
from src.advanced_features import CricketFeatureEngineer  # noqa: F401
from src.win_probability_engine import WinProbabilityEngine

APP_VERSION = "1.1.0"

app = FastAPI(
    title="Cricket Win Predictor API",
    description="Real-time cricket match win probability prediction",
    version=APP_VERSION
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load models and encoders
MODEL_PATH = "models/best_xgboost_model.pkl"
SCALER_PATH = "models/scaler.pkl"
TEAM_ENCODER_PATH = "models/team_encoder.pkl"
BATSMAN_QUALITY_PATH = "models/batsman_quality.pkl"

# Global variables for loaded models (loaded ONCE at startup)
model = None
scaler = None
team_encoder = None
feature_cols = None
mc_engine = None          # Monte Carlo engine (WinProbabilityEngine)
quality_lookup = None     # 516-player batsman quality database
_load_lock = threading.Lock()

TOTAL_BALLS = 120  # T20


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class BallEvent(BaseModel):
    """Single ball event data"""
    match_id: int
    inning: int
    batting_team: str
    bowling_team: str
    over: float
    ball: float
    batsman: str
    bowler: str
    total_runs: int
    is_wicket: bool
    cumulative_runs: Optional[float] = 0
    cumulative_wickets: Optional[float] = 0
    balls_remaining: Optional[float] = 120


class MatchState(BaseModel):
    """Current match state for prediction (XGBoost classifier path)"""
    match_id: int
    inning: int
    batting_team: str
    bowling_team: str
    overs_completed: float = Field(..., ge=0, le=20, description="Overs completed (e.g., 12.3 for 12.3 overs)")
    runs_scored: int = Field(..., ge=0, description="Current runs")
    wickets_lost: int = Field(..., ge=0, le=10, description="Wickets lost")
    target: Optional[int] = Field(None, description="Target for 2nd innings")


class PredictionResponse(BaseModel):
    """Prediction response"""
    win_probability: float
    batting_team: str
    bowling_team: str
    inning: int
    match_state: Dict
    confidence: str
    key_factors: List[str]


class BatsmanState(BaseModel):
    """Batsman at the crease. Provide 'name' (must exist in the 516-player
    database) or an explicit 'quality' (1-10) for players not in the database."""
    name: Optional[str] = Field(None, description="Player name as in the 516-player quality database")
    quality: Optional[float] = Field(None, ge=1, le=10, description="Explicit batting quality 1-10 (overrides name lookup)")
    runs: int = Field(0, ge=0, description="Runs scored by this batsman in this innings")
    balls: int = Field(0, ge=0, description="Balls faced by this batsman in this innings")


class MonteCarloRequest(BaseModel):
    """Match state for Monte Carlo simulation (win probability / final score)"""
    match_id: Optional[int] = None
    inning: int = Field(2, ge=1, le=2)
    batting_team: Optional[str] = None
    bowling_team: Optional[str] = None
    over: int = Field(..., ge=0, le=20, description="Overs completed (integer)")
    ball: int = Field(1, ge=1, le=6, description="Ball within the current over (1-6)")
    current_runs: int = Field(..., ge=0)
    current_wickets: int = Field(0, ge=0, le=10)
    target: Optional[int] = Field(None, description="Target (required for inning=2)")
    balls_remaining: Optional[int] = Field(None, ge=0, le=120,
                                          description="Derived from over/ball if omitted")
    n_simulations: int = Field(500, ge=50, le=5000, description="Number of Monte Carlo simulations")
    striker: Optional[BatsmanState] = None
    non_striker: Optional[BatsmanState] = None


class MonteCarloResponse(BaseModel):
    """Monte Carlo prediction response.
    inning=1 -> predicted_score (+ 10th/90th percentile interval).
    inning=2 -> win_probability for the batting team."""
    inning: int
    win_probability: Optional[float] = None
    predicted_score: Optional[float] = None
    confidence_interval: Optional[List[float]] = None
    simulations: int
    match_state: Dict
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Artifact loading (once, at startup)
# ---------------------------------------------------------------------------

def load_artifacts():
    """Load trained models and encoders"""
    global model, scaler, team_encoder, feature_cols

    if model is None:
        with _load_lock:
            if model is not None:
                return
            try:
                # Load XGBoost model from JSON format (portable across versions)
                model = xgb.Booster()
                model.load_model('models/best_xgboost_model.json')
                print("XGBoost model loaded from JSON")

                # Load other artifacts
                scaler = joblib.load('models/scaler.pkl')
                team_encoder = joblib.load('models/team_encoder.pkl')

                # Load feature columns
                feature_cols = joblib.load('models/feature_columns.pkl')

                print(f"All artifacts loaded successfully! ({len(feature_cols)} features)")
            except Exception as e:
                print(f"Error loading models: {e}")
                raise


def load_mc_engine():
    """Load the Monte Carlo simulation engine and the 516-player quality DB once."""
    global mc_engine, quality_lookup
    if mc_engine is None:
        with _load_lock:
            if mc_engine is not None:
                return
            mc_engine = WinProbabilityEngine()
            quality_lookup = joblib.load(BATSMAN_QUALITY_PATH)
            print(f"Monte Carlo engine loaded ({len(quality_lookup)} players in quality DB)")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load all models once on startup instead of per-request."""
    load_artifacts()
    load_mc_engine()
    yield

app.router.lifespan_context = lifespan


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "message": "Cricket Win Predictor API",
        "version": APP_VERSION,
        "endpoints": {
            "/predict": "POST - Win probability via XGBoost classifier",
            "/predict/montecarlo": "POST - Win probability / final score via Monte Carlo simulation",
            "/predict_batch": "POST - Batch XGBoost predictions",
            "/players": "GET - Search the 516-player batting quality database",
            "/health": "GET - Health check",
            "/features": "GET - List important features",
            "/teams": "GET - List all teams"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "scaler_loaded": scaler is not None,
        "mc_engine_loaded": mc_engine is not None,
        "players_loaded": len(quality_lookup) if quality_lookup is not None else 0
    }


@app.get("/teams")
async def get_teams():
    """Get list of all teams in the dataset"""
    if team_encoder is None:
        load_artifacts()

    teams = team_encoder.classes_.tolist()
    return {"teams": teams}


@app.get("/players")
async def get_players(search: Optional[str] = Query(None, description="Substring filter on player name"),
                      limit: int = Query(50, ge=1, le=516)):
    """Search the historical batsman quality database (516 players)"""
    if quality_lookup is None:
        load_mc_engine()

    names = sorted(quality_lookup.keys())
    if search:
        needle = search.lower()
        names = [n for n in names if needle in n.lower()]
    names = names[:limit]
    return {
        "count": len(names),
        "players": [{"name": n, "quality": round(float(quality_lookup[n]), 2)} for n in names]
    }


@app.get("/features")
async def get_important_features(top_n: int = 10):
    """Get top important features from the model"""
    if model is None:
        load_artifacts()

    # Get feature importance from the XGBoost Booster.
    # (native Booster has no feature_importances_; get_score('gain') gives the
    # per-feature average gain, normalized here to sum to 1 for comparability)
    raw_scores = model.get_score(importance_type='gain')
    gains = {f: raw_scores.get(f, 0.0) for f in feature_cols}
    total = sum(gains.values()) or 1.0
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': [g / total for g in gains.values()]
    }).sort_values('importance', ascending=False).head(top_n)

    return {
        "top_features": importance.to_dict('records'),
        "model_type": "XGBoost"
    }


@app.post("/predict", response_model=PredictionResponse)
async def predict(match_state: MatchState):
    """Predict win probability for current match state (XGBoost classifier)."""
    # Validate inputs (raise 400s before entering the model try/except so
    # they are not converted to 500s)
    if match_state.batting_team not in team_encoder.classes_:
        raise HTTPException(status_code=400, detail=f"Unknown batting team: {match_state.batting_team}")

    if match_state.bowling_team not in team_encoder.classes_:
        raise HTTPException(status_code=400, detail=f"Unknown bowling team: {match_state.bowling_team}")

    if match_state.inning == 2 and not match_state.target:
        raise HTTPException(status_code=400, detail="target is required for second-innings predictions")

    try:
        # Calculate derived features
        overs, balls = divmod(match_state.overs_completed, 1)
        balls = round(balls * 10)
        balls_completed = int(overs * 6 + balls)
        balls_remaining = TOTAL_BALLS - balls_completed

        # Calculate run rate
        current_rr = match_state.runs_scored / (match_state.overs_completed if match_state.overs_completed > 0 else 0.1)

        # Calculate required run rate for 2nd innings
        required_rr = 0
        rr_difference = 0
        runs_required = 0

        if match_state.inning == 2 and match_state.target:
            runs_required = match_state.target - match_state.runs_scored
            if runs_required > 0 and balls_remaining > 0:
                required_rr = runs_required / (balls_remaining / 6)
                rr_difference = required_rr - current_rr

        # Create feature vector
        features = {
            'inning': match_state.inning,
            # NOTE: 'inning.1' is a duplicate of 'inning' that was introduced
            # by a CSV round-trip when feature_columns.pkl was generated; the
            # trained model expects all 30 columns including this one, with the
            # same value as 'inning' (verified against training data).
            'inning.1': match_state.inning,
            'over': match_state.overs_completed,
            'ball': balls,
            'cumulative_runs': match_state.runs_scored,
            'cumulative_wickets': match_state.wickets_lost,
            'current_rr': current_rr,
            'projected_score': current_rr * 20,
            'runs_required': runs_required,
            'required_rr': required_rr,
            'rr_difference': rr_difference,
            'wickets_in_hand': 10 - match_state.wickets_lost,
            'balls_remaining': balls_remaining,
            'time_remaining': balls_remaining / TOTAL_BALLS,
            'wickets_remaining_norm': (10 - match_state.wickets_lost) / 10,
            'partnership_runs': 0,  # These would need historical data
            'partnership_balls': 0,
            'partnership_rr': 0,
            'over_dot_pct': 0,
            'over_boundaries': 0,
            'over_sixes': 0,
            'last_5_balls_runs': 0,
            'last_10_balls_wickets': 0,
            'bowler_economy': 0,
            'bowler_last_12_runs': 0,
            'bowler_last_12_wickets': 0,
            'batsman_sr': 0,
            'batsman_last_6_sr': 0,
            'is_powerplay': 1 if match_state.overs_completed <= 6 else 0,
            'is_middle_overs': 1 if 7 <= match_state.overs_completed <= 15 else 0,
            'is_death_overs': 1 if match_state.overs_completed >= 16 else 0
        }

        # Create DataFrame with correct feature order
        feature_df = pd.DataFrame([features])[feature_cols]

        # Scale features
        feature_scaled = scaler.transform(feature_df)

        # Predict probability
        # Convert to DMatrix for XGBoost
        dmatrix = xgb.DMatrix(feature_scaled)
        win_prob = float(model.predict(dmatrix)[0])

        # Determine confidence level
        if win_prob > 0.8 or win_prob < 0.2:
            confidence = "High"
        elif win_prob > 0.6 or win_prob < 0.4:
            confidence = "Medium"
        else:
            confidence = "Low"

        # Key factors affecting prediction
        key_factors = []
        if match_state.inning == 1:
            if current_rr > 8.5:
                key_factors.append("🔥 Batting team scoring at explosive rate")
            elif current_rr < 6:
                key_factors.append("⚠️ Batting team struggling with run rate")
        else:
            if runs_required < 30 and match_state.wickets_lost < 3:
                key_factors.append("🎯 Easy chase with plenty of wickets in hand")
            elif runs_required > 60 and match_state.wickets_lost > 5:
                key_factors.append("🏃 Tough chase with limited wickets")
            elif required_rr > 10:
                key_factors.append("⚡ High required run rate")

        if match_state.wickets_lost == 0:
            key_factors.append("🏏 All wickets in hand - batting strong")
        elif match_state.wickets_lost > 5:
            key_factors.append("⚠️ Lower order at crease")

        return PredictionResponse(
            win_probability=round(float(win_prob), 3),
            batting_team=match_state.batting_team,
            bowling_team=match_state.bowling_team,
            inning=match_state.inning,
            match_state=match_state.model_dump(),
            confidence=confidence,
            key_factors=key_factors if key_factors else ["Match evenly poised"]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")


def _resolve_batsman(batsman: Optional[BatsmanState], default_quality: float,
                     field_name: str) -> tuple:
    """Resolve a batsman's quality: explicit quality > name lookup > default.
    Raises 400 for unknown player names without an explicit quality."""
    if batsman is None:
        return default_quality, 0, 0, "default"

    quality = None
    source = "default"
    if batsman.name:
        quality = quality_lookup.get(batsman.name)
        if quality is not None:
            source = f"database:{batsman.name}"
        elif batsman.quality is None:
            raise HTTPException(
                status_code=400,
                detail=(f"Unknown player '{batsman.name}' in {field_name}: not found in the "
                        f"{len(quality_lookup)}-player quality database. "
                        f"Provide an explicit 'quality' (1-10) for this player.")
            )

    if batsman.quality is not None:
        quality = float(batsman.quality)
        source = "explicit"

    if quality is None:
        quality = default_quality

    return quality, batsman.runs, batsman.balls, source


@app.post("/predict/montecarlo", response_model=MonteCarloResponse)
def predict_montecarlo(request: MonteCarloRequest):
    """Win probability (inning=2) or final-score prediction (inning=1) via
    Monte Carlo simulation over the ball-outcome Random Forest model, with
    striker/non-striker quality adjustment from the 516-player database.

    NOTE: synchronous endpoint - FastAPI runs it on the threadpool so the
    event loop is not blocked during simulations.
    """
    if mc_engine is None:
        load_mc_engine()

    # --- validation -------------------------------------------------------
    if request.batting_team and request.batting_team not in team_encoder.classes_:
        raise HTTPException(status_code=400, detail=f"Unknown batting team: {request.batting_team}")
    if request.bowling_team and request.bowling_team not in team_encoder.classes_:
        raise HTTPException(status_code=400, detail=f"Unknown bowling team: {request.bowling_team}")

    if request.inning == 2:
        if request.target is None:
            raise HTTPException(status_code=400, detail="target is required for second-innings predictions")
        if request.target <= 0:
            raise HTTPException(status_code=400, detail="target must be a positive number")
        if request.current_runs >= request.target:
            raise HTTPException(status_code=400,
                                detail="current_runs >= target: the chase is already complete")

    balls_remaining = request.balls_remaining
    if balls_remaining is None:
        balls_remaining = (20 - request.over) * 6 - request.ball + 1
    if request.inning == 2 and balls_remaining <= 0:
        raise HTTPException(status_code=400, detail="no balls remaining in the innings")

    striker_quality, striker_runs, striker_balls, striker_src = \
        _resolve_batsman(request.striker, default_quality=7.0, field_name="striker")
    ns_quality, ns_runs, ns_balls, ns_src = \
        _resolve_batsman(request.non_striker, default_quality=5.0, field_name="non_striker")

    # --- match state in the engine's expected schema -----------------------
    overs_dec = request.over + request.ball / 10
    current_rr = request.current_runs / overs_dec if overs_dec > 0 else 0.0

    state = {
        'inning': request.inning,
        'over': request.over,
        'ball': request.ball,
        'current_runs': request.current_runs,
        'current_wickets': request.current_wickets,
        'target': request.target if request.inning == 2 else None,
        'balls_remaining': balls_remaining,
        'current_run_rate': current_rr
    }

    try:
        result = mc_engine.predict_win_probability(
            state,
            n_simulations=request.n_simulations,
            striker_quality=striker_quality, striker_runs=striker_runs, striker_balls=striker_balls,
            non_striker_quality=ns_quality, non_striker_runs=ns_runs, non_striker_balls=ns_balls
        )
    except HTTPException:
        raise
    except Exception as e:
        # Never fabricate a probability when the simulation fails
        raise HTTPException(status_code=500, detail=f"Monte Carlo simulation failed: {e}")

    quality_sources = {"striker": striker_src, "non_striker": ns_src}

    if request.inning == 1:
        all_scores = result['all_scores']
        return MonteCarloResponse(
            inning=1,
            predicted_score=round(float(np.mean(all_scores)), 1),
            confidence_interval=[round(float(np.percentile(all_scores, 10)), 1),
                                 round(float(np.percentile(all_scores, 90)), 1)],
            simulations=request.n_simulations,
            match_state={**state, "quality_sources": quality_sources},
            note="Final-score prediction for the batting team's innings (10th-90th percentile interval)."
        )

    return MonteCarloResponse(
        inning=2,
        win_probability=round(float(result['win_probability']), 4),
        simulations=request.n_simulations,
        match_state={**state, "quality_sources": quality_sources},
        note="Probability that the batting team wins the chase."
    )


@app.post("/predict_batch")
async def predict_batch(match_states: List[MatchState]):
    """Predict win probabilities for multiple match states"""
    try:
        predictions = []
        for state in match_states:
            try:
                result = await predict(state)
                predictions.append(result.model_dump())
            except HTTPException as e:
                predictions.append({
                    "error": e.detail,
                    "match_state": state.model_dump()
                })
            except Exception as e:
                predictions.append({
                    "error": str(e),
                    "match_state": state.model_dump()
                })

        return {"predictions": predictions}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("api.app:app", host="0.0.0.0", port=8000)
