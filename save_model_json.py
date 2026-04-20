import joblib
import xgboost as xgb
import numpy as np

# Load your model
model = joblib.load('models/best_xgboost_model.pkl')

# Save in XGBoost's portable JSON format
model.save_model('models/best_xgboost_model.json')
print("✅ Model saved as JSON")

# Also save feature names if you have them
try:
    import pandas as pd
    train_data = pd.read_csv('data/processed/modeling_data.csv')
    feature_cols = [col for col in train_data.columns 
                   if col not in ['target', 'match_id', 'inning', 'batting_team', 'bowling_team']]
    joblib.dump(feature_cols, 'models/feature_columns.pkl')
    print("✅ Feature columns saved")
except:
    print("⚠️ Couldn't save feature columns")