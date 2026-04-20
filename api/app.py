from fastapi import FastAPI, HTTPException
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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import your feature engineering
from src.advanced_features import CricketFeatureEngineer

app = FastAPI(
    title="Cricket Win Predictor API",
    description="Real-time cricket match win probability prediction",
    version="1.0.0"
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

# Global variables for loaded models
model = None
scaler = None
team_encoder = None
feature_cols = None

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
    """Current match state for prediction"""
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

def load_artifacts():
    """Load trained models and encoders"""
    global model, scaler, team_encoder, feature_cols
    
    if model is None:
        try:
            # Load XGBoost model from JSON format (portable across versions)
            model = xgb.Booster()
            model.load_model('models/best_xgboost_model.json')
            print("✅ XGBoost model loaded from JSON")
            
            # Load other artifacts
            scaler = joblib.load('models/scaler.pkl')
            team_encoder = joblib.load('models/team_encoder.pkl')
            
            # Load feature columns
            feature_cols = joblib.load('models/feature_columns.pkl')
            
            print("✅ All artifacts loaded successfully!")
            print(f"✅ Loaded {len(feature_cols)} features")
        except Exception as e:
            print(f"❌ Error loading models: {e}")
            raise
@app.on_event("startup")
async def startup_event():
    """Load models on startup"""
    load_artifacts()

@app.get("/")
async def root():
    return {
        "message": "Cricket Win Predictor API",
        "version": "1.0.0",
        "endpoints": {
            "/predict": "POST - Get win probability",
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
        "scaler_loaded": scaler is not None
    }

@app.get("/teams")
async def get_teams():
    """Get list of all teams in the dataset"""
    if team_encoder is None:
        load_artifacts()
    
    teams = team_encoder.classes_.tolist()
    return {"teams": teams}

@app.get("/features")
async def get_important_features(top_n: int = 10):
    """Get top important features from the model"""
    if model is None:
        load_artifacts()
    
    # Get feature importance from XGBoost
    importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False).head(top_n)
    
    return {
        "top_features": importance.to_dict('records'),
        "model_type": "XGBoost"
    }

@app.post("/predict", response_model=PredictionResponse)
async def predict(match_state: MatchState):
    """Predict win probability for current match state"""
    try:
        # Validate inputs
        if match_state.batting_team not in team_encoder.classes_:
            raise HTTPException(status_code=400, detail=f"Unknown batting team: {match_state.batting_team}")
        
        if match_state.bowling_team not in team_encoder.classes_:
            raise HTTPException(status_code=400, detail=f"Unknown bowling team: {match_state.bowling_team}")
        
        # Calculate derived features
        overs, balls = divmod(match_state.overs_completed, 1)
        balls = round(balls * 10)
        balls_completed = int(overs * 6 + balls)
        balls_remaining = 120 - balls_completed
        
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
            'time_remaining': balls_remaining / 120,
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
            match_state=match_state.dict(),
            confidence=confidence,
            key_factors=key_factors if key_factors else ["Match evenly poised"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/predict_batch")
async def predict_batch(match_states: List[MatchState]):
    """Predict win probabilities for multiple match states"""
    try:
        predictions = []
        for state in match_states:
            try:
                result = await predict(state)
                predictions.append(result.dict())
            except Exception as e:
                predictions.append({
                    "error": str(e),
                    "match_state": state.dict()
                })
        
        return {"predictions": predictions}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)