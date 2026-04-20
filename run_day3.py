"""
DAY 3: MODEL BUILDING - COMPLETE AND WORKING
Run this script to build all three models
"""

import pandas as pd
import numpy as np
import joblib
import os
import json
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score, accuracy_score, classification_report
import lightgbm as lgb
from sklearn.ensemble import RandomForestClassifier
import warnings
warnings.filterwarnings('ignore')

print("="*80)
print("DAY 3: MODEL BUILDING - COMPLETE")
print("="*80)

# ============================================================================
# 1. CREATE DIRECTORIES
# ============================================================================
print("\n1. 📁 CREATING DIRECTORIES...")
directories = [
    'models/first_innings',
    'models/ball_outcome',
    'models/win_probability',
    'reports/figures',
    'reports/model_metrics'
]

for dir_path in directories:
    os.makedirs(dir_path, exist_ok=True)
    print(f"   ✅ Created: {dir_path}")

# ============================================================================
# 2. LOAD DATA
# ============================================================================
print("\n2. 📂 LOADING DATA...")
try:
    first_innings = pd.read_csv('data/processed/first_innings_model_ready.csv')
    second_innings = pd.read_csv('data/processed/second_innings_model_ready.csv')
    match_summary = pd.read_csv('data/processed/match_summary.csv')
    
    print(f"   ✅ First innings: {first_innings.shape}")
    print(f"   ✅ Second innings: {second_innings.shape}")
    print(f"   ✅ Match summary: {match_summary.shape}")
    
except FileNotFoundError as e:
    print(f"   ❌ Error: {e}")
    print("   Please run Day 2 feature engineering first!")
    exit()

# ============================================================================
# 3. TRAIN FIRST INNINGS MODEL (FIXED)
# ============================================================================
print("\n3. 🎯 TRAINING FIRST INNINGS SCORE PREDICTOR")
print("   " + "-"*50)

# Define a SIMPLE, FIXED set of features
first_features = [
    'over',
    'ball',
    'cumulative_runs',
    'cumulative_wickets',
    'balls_remaining',
    'current_run_rate',
    'is_powerplay',
    'is_death',
    'runs_last_5_overs',
    'wickets_last_5_overs',
    'partnership_runs'
]

# Check and create missing features
for feature in first_features:
    if feature not in first_innings.columns:
        print(f"   Creating missing feature: {feature}")
        if feature == 'balls_remaining':
            first_innings['balls_bowled'] = (first_innings['over'] * 6) + first_innings['ball']
            first_innings['balls_remaining'] = 120 - first_innings['balls_bowled']
        elif feature == 'current_run_rate':
            first_innings['overs_completed'] = first_innings['over'] + first_innings['ball'] / 10
            first_innings['current_run_rate'] = first_innings['cumulative_runs'] / first_innings['overs_completed'].replace(0, 1)
            first_innings['current_run_rate'] = first_innings['current_run_rate'].fillna(0)
        elif feature == 'is_powerplay':
            first_innings['is_powerplay'] = (first_innings['over'] < 6).astype(int)
        elif feature == 'is_death':
            first_innings['is_death'] = (first_innings['over'] >= 15).astype(int)
        elif feature == 'runs_last_5_overs':
            first_innings['runs_last_5_overs'] = 30  # Default value
        elif feature == 'wickets_last_5_overs':
            first_innings['wickets_last_5_overs'] = 1  # Default value
        elif feature == 'partnership_runs':
            first_innings['partnership_runs'] = 20  # Default value

# Prepare data
X_first = first_innings[first_features].copy()
y_first = first_innings['final_total']

print(f"   Using {len(first_features)} features")
print(f"   Data shape: X={X_first.shape}, y={y_first.shape}")

# Split by match
match_ids = first_innings['match_id'].unique()
train_matches, test_matches = train_test_split(match_ids, test_size=0.2, random_state=42)

train_mask = first_innings['match_id'].isin(train_matches)
test_mask = first_innings['match_id'].isin(test_matches)

X_train = X_first[train_mask]
X_test = X_first[test_mask]
y_train = y_first[train_mask]
y_test = y_first[test_mask]

print(f"   Training: {len(X_train):,} samples")
print(f"   Testing: {len(X_test):,} samples")

# Train LightGBM
print("\n   Training LightGBM model...")
lgb_model = lgb.LGBMRegressor(
    objective='regression',
    metric='mae',
    learning_rate=0.05,
    num_leaves=31,
    max_depth=7,
    n_estimators=200,
    random_state=42,
    verbose=-1
)

lgb_model.fit(X_train, y_train)

# Evaluate
y_pred = lgb_model.predict(X_test)
mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)

print(f"\n   📈 Performance:")
print(f"     MAE: {mae:.2f} runs")
print(f"     R²: {r2:.4f}")

# Save model
joblib.dump(lgb_model, 'models/first_innings/lightgbm_model.pkl')
joblib.dump(list(X_train.columns), 'models/first_innings/feature_columns.pkl')

print("\n   ✅ First innings model saved!")

# ============================================================================
# 4. TRAIN BALL-OUTCOME MODEL
# ============================================================================
print("\n4. 🎯 TRAINING BALL-OUTCOME PREDICTOR")
print("   " + "-"*50)

# Combine data
all_balls = pd.concat([first_innings, second_innings], ignore_index=True)

# Create outcome column
def get_outcome(row):
    if 'is_wicket' in row and row['is_wicket'] == 1:
        return 7  # Wicket
    elif 'batsman_runs' in row:
        runs = row['batsman_runs']
        if runs == 0: return 0
        elif runs == 1: return 1
        elif runs == 2: return 2
        elif runs == 3: return 3
        elif runs == 4: return 4
        elif runs == 6: return 6
        else: return 0
    else:
        return 0  # Default to dot

all_balls['outcome'] = all_balls.apply(get_outcome, axis=1)

# Define simple features
ball_features = [
    'over',
    'ball',
    'cumulative_runs',
    'cumulative_wickets',
    'current_run_rate',
    'is_powerplay',
    'is_death',
    'runs_needed'
]

# Ensure features exist
for feature in ball_features:
    if feature not in all_balls.columns:
        if feature == 'current_run_rate':
            all_balls['overs_completed'] = all_balls['over'] + all_balls['ball'] / 10
            all_balls['current_run_rate'] = all_balls['cumulative_runs'] / all_balls['overs_completed'].replace(0, 1)
        elif feature == 'is_powerplay':
            all_balls['is_powerplay'] = (all_balls['over'] < 6).astype(int)
        elif feature == 'is_death':
            all_balls['is_death'] = (all_balls['over'] >= 15).astype(int)
        elif feature == 'runs_needed':
            all_balls['runs_needed'] = 0  # Default for first innings

# Prepare data
X_ball = all_balls[ball_features].copy()
y_ball = all_balls['outcome']

# Split by match
ball_match_ids = all_balls['match_id'].unique()
ball_train_matches, ball_test_matches = train_test_split(ball_match_ids, test_size=0.2, random_state=42)

ball_train_mask = all_balls['match_id'].isin(ball_train_matches)
ball_test_mask = all_balls['match_id'].isin(ball_test_matches)

X_ball_train = X_ball[ball_train_mask]
X_ball_test = X_ball[ball_test_mask]
y_ball_train = y_ball[ball_train_mask]
y_ball_test = y_ball[ball_test_mask]

print(f"   Training: {len(X_ball_train):,} balls")
print(f"   Testing: {len(X_ball_test):,} balls")

# Train Random Forest
print("\n   Training Random Forest model...")
rf_model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    random_state=42,
    n_jobs=-1,
    class_weight='balanced'
)

rf_model.fit(X_ball_train, y_ball_train)

# Evaluate
y_ball_pred = rf_model.predict(X_ball_test)
accuracy = accuracy_score(y_ball_test, y_ball_pred)

print(f"\n   📈 Performance:")
print(f"     Accuracy: {accuracy:.4f}")

# Save model
joblib.dump(rf_model, 'models/ball_outcome/random_forest_model.pkl')
joblib.dump(list(X_ball_train.columns), 'models/ball_outcome/feature_columns.pkl')

print("\n   ✅ Ball outcome model saved!")

# ============================================================================
# 5. CREATE WIN PROBABILITY ENGINE
# ============================================================================
print("\n5. 🎯 CREATING WIN PROBABILITY ENGINE")
print("   " + "-"*50)

class WinProbabilityEngine:
    def __init__(self):
        self.first_model = lgb_model
        self.ball_model = rf_model
        self.first_features = list(X_train.columns)
        self.ball_features = list(X_ball_train.columns)
    
    def predict_first_innings(self, state):
        """Predict final score for first innings"""
        # Create feature vector
        features = {}
        for feat in self.first_features:
            if feat in state:
                features[feat] = state[feat]
            else:
                features[feat] = 0  # Default
        
        # Convert to DataFrame
        X = pd.DataFrame([features])[self.first_features]
        
        # Predict
        score = self.first_model.predict(X)[0]
        
        return {
            'predicted_score': float(score),
            'current_score': state.get('cumulative_runs', 0),
            'current_wickets': state.get('cumulative_wickets', 0)
        }
    
    def predict_win_probability(self, state, n_simulations=1000):
        """Predict win probability for second innings"""
        if state.get('inning', 2) == 1:
            return self.predict_first_innings(state)
        
        # For second innings
        current_runs = state.get('cumulative_runs', 0)
        current_wickets = state.get('cumulative_wickets', 0)
        target = state.get('target', 0)
        balls_remaining = state.get('balls_remaining', 
                                   (20 - state.get('over', 0)) * 6 - state.get('ball', 1))
        
        if target <= 0:
            return {'win_probability': 0.0, 'error': 'Invalid target'}
        
        wins = 0
        
        for _ in range(n_simulations):
            runs = current_runs
            wickets = current_wickets
            balls = balls_remaining
            
            while balls > 0 and wickets < 10:
                # Create ball state
                ball_state = {
                    'over': state.get('over', 0) + (balls_remaining - balls) // 6,
                    'ball': 6 - ((balls_remaining - balls) % 6),
                    'cumulative_runs': runs,
                    'cumulative_wickets': wickets,
                    'current_run_rate': runs / ((120 - balls) / 6) if (120 - balls) > 0 else 0,
                    'is_powerplay': 1 if state.get('over', 0) + (balls_remaining - balls) // 6 < 6 else 0,
                    'is_death': 1 if state.get('over', 0) + (balls_remaining - balls) // 6 >= 15 else 0,
                    'runs_needed': max(0, target - runs)
                }
                
                # Get ball outcome
                X_ball_state = pd.DataFrame([ball_state])[self.ball_features]
                if hasattr(self.ball_model, 'predict_proba'):
                    probs = self.ball_model.predict_proba(X_ball_state)[0]
                    outcome = np.random.choice(len(probs), p=probs)
                else:
                    outcome = self.ball_model.predict(X_ball_state)[0]
                
                # Update
                if outcome == 7:  # Wicket
                    wickets += 1
                elif outcome in [1, 2, 3, 4, 6]:
                    runs += outcome
                
                balls -= 1
                
                # Check win
                if runs >= target:
                    break
            
            if runs >= target:
                wins += 1
        
        win_prob = wins / n_simulations
        
        return {
            'win_probability': float(win_prob),
            'current_score': current_runs,
            'current_wickets': current_wickets,
            'target': target,
            'runs_needed': target - current_runs,
            'balls_remaining': balls_remaining,
            'simulations': n_simulations,
            'wins': wins
        }

# Create and save engine
engine = WinProbabilityEngine()
joblib.dump(engine, 'models/win_probability/engine.pkl')

print("   ✅ Win probability engine created and saved!")

# ============================================================================
# 6. TEST THE MODELS
# ============================================================================
print("\n6. 🧪 TESTING MODELS")
print("   " + "-"*50)

# Test 1: First innings
print("\n   Test 1 - First Innings:")
test_state_1 = {
    'over': 10,
    'ball': 3,
    'cumulative_runs': 85,
    'cumulative_wickets': 3,
    'balls_remaining': 57,
    'current_run_rate': 8.5,
    'is_powerplay': 0,
    'is_death': 0,
    'runs_last_5_overs': 40,
    'wickets_last_5_overs': 1,
    'partnership_runs': 25
}

result_1 = engine.predict_first_innings(test_state_1)
print(f"     Current: {result_1['current_score']}/{result_1['current_wickets']} after 10.3 overs")
print(f"     Predicted final score: {result_1['predicted_score']:.1f}")

# Test 2: Second innings
print("\n   Test 2 - Second Innings:")
test_state_2 = {
    'inning': 2,
    'over': 15,
    'ball': 3,
    'cumulative_runs': 120,
    'cumulative_wickets': 4,
    'target': 162,
    'balls_remaining': 27
}

result_2 = engine.predict_win_probability(test_state_2, n_simulations=500)
print(f"     Current: {result_2['current_score']}/{result_2['current_wickets']}")
print(f"     Target: {result_2['target']}, Need: {result_2['runs_needed']} in {result_2['balls_remaining']} balls")
print(f"     Win Probability: {result_2['win_probability']:.2%}")

# ============================================================================
# 7. SAVE METADATA
# ============================================================================
print("\n7. 💾 SAVING METADATA")
print("   " + "-"*50)

metadata = {
    'models_created': {
        'first_innings_predictor': {
            'type': 'LightGBM Regressor',
            'features': first_features,
            'performance': {'mae': float(mae), 'r2': float(r2)},
            'file': 'models/first_innings/lightgbm_model.pkl'
        },
        'ball_outcome_predictor': {
            'type': 'Random Forest Classifier',
            'features': ball_features,
            'performance': {'accuracy': float(accuracy)},
            'file': 'models/ball_outcome/random_forest_model.pkl'
        },
        'win_probability_engine': {
            'type': 'Monte Carlo Simulation',
            'file': 'models/win_probability/engine.pkl'
        }
    },
    'training_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_summary': {
        'first_innings_samples': len(first_innings),
        'second_innings_samples': len(second_innings),
        'total_matches': len(match_summary),
        'training_matches': len(train_matches),
        'test_matches': len(test_matches)
    }
}

with open('models/model_metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print("   ✅ Metadata saved to models/model_metadata.json")

# ============================================================================
# COMPLETION
# ============================================================================
print("\n" + "="*80)
print("🎉 DAY 3 COMPLETED SUCCESSFULLY!")
print("="*80)
print("\n📋 MODELS CREATED:")
print("   1. First Innings Score Predictor (LightGBM)")
print("   2. Ball Outcome Predictor (Random Forest)")
print("   3. Win Probability Engine (Monte Carlo)")
print("\n📁 FILES SAVED:")
print("   • models/first_innings/lightgbm_model.pkl")
print("   • models/ball_outcome/random_forest_model.pkl")
print("   • models/win_probability/engine.pkl")
print("   • models/model_metadata.json")
print(f"\n⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")