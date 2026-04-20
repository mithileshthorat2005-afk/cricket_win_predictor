"""
First Innings Score Predictor Module
"""

import pandas as pd
import numpy as np
import joblib
import os
from typing import Dict, Tuple

class FirstInningsPredictor:
    def __init__(self, model_path: str = None):
        """
        Initialize the first innings predictor.
        
        Args:
            model_path: Path to saved LightGBM model
        """
        if model_path and os.path.exists(model_path):
            self.model = joblib.load(model_path)
            self.feature_columns = joblib.load(
                model_path.replace('lightgbm_model.pkl', 'feature_columns.pkl')
            )
        else:
            self.model = None
            self.feature_columns = None
        
        # Default feature list if no saved model
        self.default_features = [
            'over', 'ball', 'overs_completed', 'balls_remaining',
            'cumulative_runs', 'cumulative_wickets', 'wickets_remaining',
            'current_run_rate', 'phase_middle', 'phase_powerplay', 'phase_death',
            'is_powerplay', 'is_death',
            'runs_last_5_overs', 'wickets_last_5_overs', 'rr_last_5_overs',
            'partnership_runs', 'resources_remaining'
        ]
    
    def predict(self, match_state: Dict) -> Dict:
        """
        Predict final score for first innings.
        
        Args:
            match_state: Dictionary containing match state
            
        Returns:
            Dictionary with prediction results
        """
        if self.model is None:
            return self._default_prediction(match_state)
        
        # Create features
        features = self._create_features(match_state)
        
        # Ensure correct feature order
        features_df = pd.DataFrame([features])
        for col in self.feature_columns:
            if col not in features_df.columns:
                features_df[col] = 0
        
        features_df = features_df[self.feature_columns]
        
        # Make prediction
        predicted_score = self.model.predict(features_df)[0]
        
        # Add uncertainty
        n_simulations = 1000
        scores = np.random.normal(predicted_score, 15, n_simulations)
        scores = np.maximum(scores, match_state.get('current_runs', 0))
        
        return {
            'predicted_score': float(predicted_score),
            'confidence_interval': (
                float(np.percentile(scores, 10)),
                float(np.percentile(scores, 90))
            ),
            'score_range': (float(np.min(scores)), float(np.max(scores))),
            'current_score': match_state.get('current_runs', 0),
            'current_wickets': match_state.get('current_wickets', 0),
            'overs_completed': match_state.get('overs_completed', 0)
        }
    
    def _create_features(self, match_state: Dict) -> Dict:
        """Create feature dictionary from match state."""
        features = {}
        
        # Basic features
        features['over'] = match_state.get('over', 0)
        features['ball'] = match_state.get('ball', 1)
        
        # Calculate derived features
        overs_completed = match_state.get('overs_completed', 
                                         features['over'] + features['ball']/10)
        features['overs_completed'] = overs_completed
        
        balls_remaining = match_state.get('balls_remaining', 
                                         (20 - features['over']) * 6 - features['ball'])
        features['balls_remaining'] = balls_remaining
        
        current_runs = match_state.get('current_runs', 0)
        features['cumulative_runs'] = current_runs
        
        current_wickets = match_state.get('current_wickets', 0)
        features['cumulative_wickets'] = current_wickets
        features['wickets_remaining'] = 10 - current_wickets
        
        # Run rate
        if overs_completed > 0:
            features['current_run_rate'] = current_runs / overs_completed
        else:
            features['current_run_rate'] = 0
        
        # Phase features
        features['is_powerplay'] = 1 if features['over'] < 6 else 0
        features['is_death'] = 1 if features['over'] >= 15 else 0
        
        # Phase dummies
        features['phase_middle'] = 1 if 6 <= features['over'] < 15 else 0
        features['phase_powerplay'] = features['is_powerplay']
        features['phase_death'] = features['is_death']
        
        # Default values for other features
        features['runs_last_5_overs'] = match_state.get('runs_last_5_overs', 30)
        features['wickets_last_5_overs'] = match_state.get('wickets_last_5_overs', 1)
        features['rr_last_5_overs'] = match_state.get('rr_last_5_overs', 6.0)
        features['partnership_runs'] = match_state.get('partnership_runs', 20)
        
        # Resources
        features['resources_remaining'] = (
            (balls_remaining * features['wickets_remaining']) / (120 * 10)
        )
        
        return features
    
    def _default_prediction(self, match_state: Dict) -> Dict:
        """Default prediction when no model is loaded."""
        current_runs = match_state.get('current_runs', 0)
        current_wickets = match_state.get('current_wickets', 0)
        overs_completed = match_state.get('overs_completed', 0)
        
        # Simple linear projection
        if overs_completed > 0:
            projected_score = current_runs * (20 / overs_completed)
        else:
            projected_score = 160  # Default T20 average
        
        # Adjust for wickets
        wicket_factor = 1 - (current_wickets * 0.05)
        projected_score *= wicket_factor
        
        return {
            'predicted_score': float(projected_score),
            'confidence_interval': (
                float(projected_score * 0.85),
                float(projected_score * 1.15)
            ),
            'score_range': (
                float(projected_score * 0.7),
                float(projected_score * 1.3)
            ),
            'current_score': current_runs,
            'current_wickets': current_wickets,
            'overs_completed': overs_completed,
            'note': 'Using default prediction (no model loaded)'
        }

# Singleton instance
_first_innings_predictor = None

def get_first_innings_predictor(model_path: str = None):
    """Get singleton instance of first innings predictor."""
    global _first_innings_predictor
    if _first_innings_predictor is None:
        _first_innings_predictor = FirstInningsPredictor(model_path)
    return _first_innings_predictor