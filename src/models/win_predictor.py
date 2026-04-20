import pandas as pd
import numpy as np
import joblib
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
import warnings
warnings.filterwarnings('ignore')

# Try importing XGBoost and LightGBM
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
    print("✅ XGBoost loaded successfully")
except ImportError:
    XGB_AVAILABLE = False
    print("⚠️ XGBoost not available - will use Random Forest only")

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
    print("✅ LightGBM loaded successfully")
except ImportError:
    LGB_AVAILABLE = False
    print("⚠️ LightGBM not available - will use Random Forest only")

class CricketWinPredictor:
    def __init__(self, modeling_data_path):
        self.data = pd.read_csv(modeling_data_path)
        self.models = {}
        self.results = {}
        self.scaler = StandardScaler()
        self.team_encoder = LabelEncoder()
        
    def prepare_features(self):
        """Prepare features for modeling"""
        print("="*50)
        print("PREPARING FEATURES FOR MODELING")
        print("="*50)
        
        # Feature columns (exclude target and metadata)
        feature_cols = [col for col in self.data.columns 
                       if col not in ['target', 'match_id', 'inning', 'batting_team', 'bowling_team']]
        
        X = self.data[feature_cols].copy()
        y = self.data['target'].copy()
        
        # Handle any infinite values
        X = X.replace([np.inf, -np.inf], np.nan)
        X = X.fillna(0)
        
        print(f"Features shape: {X.shape}")
        print(f"Target distribution:\n{y.value_counts(normalize=True)}")
        print(f"\nNumber of features: {len(feature_cols)}")
        
        return X, y, feature_cols
    
    def temporal_train_test_split(self, X, y):
        """Split data temporally (respect match order)"""
        # Get unique matches in chronological order
        unique_matches = self.data[['match_id', 'inning']].drop_duplicates().sort_values('match_id')
        
        # Use first 70% matches for training, next 15% for validation, last 15% for test
        n_matches = len(unique_matches)
        train_idx = int(0.7 * n_matches)
        val_idx = int(0.85 * n_matches)
        
        train_matches = unique_matches.iloc[:train_idx]['match_id'].values
        val_matches = unique_matches.iloc[train_idx:val_idx]['match_id'].values
        test_matches = unique_matches.iloc[val_idx:]['match_id'].values
        
        # Create masks
        train_mask = self.data['match_id'].isin(train_matches)
        val_mask = self.data['match_id'].isin(val_matches)
        test_mask = self.data['match_id'].isin(test_matches)
        
        X_train, X_val, X_test = X[train_mask], X[val_mask], X[test_mask]
        y_train, y_val, y_test = y[train_mask], y[val_mask], y[test_mask]
        
        print(f"\nTemporal Split:")
        print(f"Training matches: {len(train_matches)} ({len(X_train)} balls)")
        print(f"Validation matches: {len(val_matches)} ({len(X_val)} balls)")
        print(f"Test matches: {len(test_matches)} ({len(X_test)} balls)")
        
        return X_train, X_val, X_test, y_train, y_val, y_test
    
    def build_xgboost_model(self, X_train, y_train, X_val, y_val):
        """Build XGBoost model"""
        if not XGB_AVAILABLE:
            return None
            
        print("\n" + "="*50)
        print("TRAINING XGBOOST MODEL")
        print("="*50)
        
        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            eval_metric='logloss',
            early_stopping_rounds=50,
            verbosity=0
        )
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=50
        )
        
        self.models['xgboost'] = model
        return model
    
    def build_lightgbm_model(self, X_train, y_train, X_val, y_val):
        """Build LightGBM model"""
        if not LGB_AVAILABLE:
            return None
            
        print("\n" + "="*50)
        print("TRAINING LIGHTGBM MODEL")
        print("="*50)
        
        model = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            eval_metric='auc',
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]
        )
        
        self.models['lightgbm'] = model
        return model
    
    def build_random_forest_model(self, X_train, y_train):
        """Build Random Forest model"""
        print("\n" + "="*50)
        print("TRAINING RANDOM FOREST MODEL")
        print("="*50)
        
        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_split=20,
            min_samples_leaf=10,
            random_state=42,
            n_jobs=-1,
            verbose=0
        )
        
        model.fit(X_train, y_train)
        self.models['random_forest'] = model
        return model
    
    def build_ensemble_model(self, X_train, y_train, X_val, y_val):
        """Build ensemble of available models"""
        print("\n" + "="*50)
        print("BUILDING ENSEMBLE MODEL")
        print("="*50)
        
        estimators = []
        weights = []
        
        if XGB_AVAILABLE:
            xgb_model = xgb.XGBClassifier(
                n_estimators=200, max_depth=5, learning_rate=0.05,
                random_state=42, n_jobs=-1
            )
            estimators.append(('xgb', xgb_model))
            weights.append(2)
            print("✅ Added XGBoost to ensemble")
            
        if LGB_AVAILABLE:
            lgb_model = lgb.LGBMClassifier(
                n_estimators=200, max_depth=5, learning_rate=0.05,
                random_state=42, n_jobs=-1, verbose=-1
            )
            estimators.append(('lgb', lgb_model))
            weights.append(2)
            print("✅ Added LightGBM to ensemble")
        
        # Always add Random Forest
        rf_model = RandomForestClassifier(
            n_estimators=150, max_depth=8, random_state=42, n_jobs=-1
        )
        estimators.append(('rf', rf_model))
        weights.append(1)
        
        if len(estimators) < 2:
            print("⚠️ Not enough models for ensemble, using Random Forest only")
            return self.build_random_forest_model(X_train, y_train)
        
        ensemble = VotingClassifier(
            estimators=estimators,
            voting='soft',
            weights=weights
        )
        
        ensemble.fit(X_train, y_train)
        self.models['ensemble'] = ensemble
        return ensemble
    
    def evaluate_model(self, model, X_test, y_test, model_name):
        """Evaluate model performance"""
        if model is None:
            return None
            
        print(f"\n📊 EVALUATING {model_name.upper()}")
        print("-"*30)
        
        y_pred_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_pred_prob > 0.5).astype(int)
        
        accuracy = accuracy_score(y_test, y_pred)
        auc = roc_auc_score(y_test, y_pred_prob)
        precision = precision_score(y_test, y_pred)
        recall = recall_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred)
        
        self.results[model_name] = {
            'accuracy': accuracy,
            'auc': auc,
            'precision': precision,
            'recall': recall,
            'f1': f1
        }
        
        print(f"Accuracy:  {accuracy:.4f}")
        print(f"AUC:       {auc:.4f}")
        print(f"Precision: {precision:.4f}")
        print(f"Recall:    {recall:.4f}")
        print(f"F1 Score:  {f1:.4f}")
        
        cm = confusion_matrix(y_test, y_pred)
        print(f"\nConfusion Matrix:")
        print(f"TN: {cm[0,0]:5d}  FP: {cm[0,1]:5d}")
        print(f"FN: {cm[1,0]:5d}  TP: {cm[1,1]:5d}")
        
        return self.results[model_name]
    
    def get_feature_importance(self, model, feature_cols):
        """Get feature importance"""
        if model is None:
            return None
            
        if hasattr(model, 'feature_importances_'):
            importance = pd.DataFrame({
                'feature': feature_cols,
                'importance': model.feature_importances_
            }).sort_values('importance', ascending=False)
            
            print("\n🔑 TOP 10 IMPORTANT FEATURES:")
            print(importance.head(10).to_string(index=False))
            return importance
        return None
    
    def run_pipeline(self):
        """Run the complete modeling pipeline"""
        # 1. Prepare features
        X, y, feature_cols = self.prepare_features()
        
        # 2. Temporal split
        X_train, X_val, X_test, y_train, y_val, y_test = self.temporal_train_test_split(X.values, y)
        
        # 3. Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)
        X_test_scaled = self.scaler.transform(X_test)
        
        # 4. Build and evaluate models
        # Always train Random Forest
        rf_model = self.build_random_forest_model(X_train_scaled, y_train)
        self.evaluate_model(rf_model, X_test_scaled, y_test, 'random_forest')
        self.get_feature_importance(rf_model, feature_cols)
        
        # Train XGBoost if available
        if XGB_AVAILABLE:
            xgb_model = self.build_xgboost_model(X_train_scaled, y_train, X_val_scaled, y_val)
            if xgb_model:
                self.evaluate_model(xgb_model, X_test_scaled, y_test, 'xgboost')
                self.get_feature_importance(xgb_model, feature_cols)
        
        # Train LightGBM if available
        if LGB_AVAILABLE:
            lgb_model = self.build_lightgbm_model(X_train_scaled, y_train, X_val_scaled, y_val)
            if lgb_model:
                self.evaluate_model(lgb_model, X_test_scaled, y_test, 'lightgbm')
                self.get_feature_importance(lgb_model, feature_cols)
        
        # Build ensemble
        ensemble_model = self.build_ensemble_model(X_train_scaled, y_train, X_val_scaled, y_val)
        if ensemble_model:
            self.evaluate_model(ensemble_model, X_test_scaled, y_test, 'ensemble')
        
        # 5. Compare models
        self.compare_models()
        self.save_best_model()
        
        return self.results
    
    def compare_models(self):
        """Compare all model performances"""
        print("\n" + "="*50)
        print("📈 MODEL COMPARISON")
        print("="*50)
        
        comparison = pd.DataFrame(self.results).T[['accuracy', 'auc', 'precision', 'recall', 'f1']]
        print(comparison.round(4))
        
        best_model = comparison['auc'].idxmax()
        print(f"\n🏆 Best Model: {best_model.upper()} with AUC = {comparison.loc[best_model, 'auc']:.4f}")
        
        return comparison
    
    def save_best_model(self):
        """Save the best performing model"""
        if not self.results:
            print("❌ No models to save")
            return
            
        best_model_name = max(self.results, key=lambda x: self.results[x]['auc'])
        best_model = self.models[best_model_name]
        
        import os
        os.makedirs('models', exist_ok=True)
        
        joblib.dump(best_model, f'models/best_{best_model_name}_model.pkl')
        joblib.dump(self.scaler, 'models/scaler.pkl')
        joblib.dump(self.team_encoder, 'models/team_encoder.pkl')
        
        print(f"\n💾 Saved best model: {best_model_name}")
        print(f"💾 Model saved to: models/best_{best_model_name}_model.pkl")

# Run the pipeline
if __name__ == "__main__":
    print("\n🏏 CRICKET WIN PREDICTOR - MODEL TRAINING")
    print("="*50)
    
    try:
        predictor = CricketWinPredictor('data/processed/modeling_data.csv')
        results = predictor.run_pipeline()
        print("\n✅ Model building complete!")
    except FileNotFoundError:
        print("❌ Could not find modeling_data.csv. Please run feature engineering first.")
    except Exception as e:
        print(f"❌ Error: {e}")