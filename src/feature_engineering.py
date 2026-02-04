"""
feature_engineering.py
Advanced feature engineering for cricket win prediction
"""

import pandas as pd
import numpy as np
from tqdm import tqdm

# ========== ADD THESE FUNCTIONS TO YOUR EXISTING FILE ==========

def create_advanced_features(df, total_overs=20):
    """
    Create advanced match-state features
    Args:
        df: DataFrame with basic features (cumulative_runs, cumulative_wickets)
        total_overs: 20 for T20, 50 for ODI
    Returns:
        DataFrame with advanced features
    """
    print("Starting advanced feature engineering...")
    df = df.copy()
    
    # 1. Basic match state calculations
    print("Step 1: Basic match state...")
    df = df.sort_values(['match_id', 'inning', 'over', 'ball'])
    df['balls_bowled'] = (df['over'] * 6) + df['ball']
    df['balls_remaining'] = (total_overs * 6) - df['balls_bowled']
    df['wickets_remaining'] = 10 - df['cumulative_wickets']
    
    # Overs as float (e.g., 5.3 for over 5 ball 3)
    df['overs_completed'] = df['over'] + df['ball'] / 10
    
    # Current run rate
    df['current_run_rate'] = np.where(df['overs_completed'] > 0,
                                     df['cumulative_runs'] / df['overs_completed'],
                                     0)
    
    # 2. Get first innings totals for targets
    print("Step 2: Calculating match targets...")
    match_targets = {}
    for match_id in df['match_id'].unique():
        match_df = df[df['match_id'] == match_id]
        first_inn = match_df[match_df['inning'] == 1]
        if not first_inn.empty:
            # Get the last cumulative runs value
            target = first_inn['cumulative_runs'].iloc[-1]
            match_targets[match_id] = target
    
    # Add target column
    df['first_innings_total'] = df['match_id'].map(match_targets).fillna(0)
    df['target'] = df['first_innings_total'] + 1  # Need 1 more to win
    
    # 3. Chasing features (only for 2nd innings)
    print("Step 3: Chasing features...")
    df['runs_needed'] = np.where(df['inning'] == 2,
                                np.maximum(0, df['target'] - df['cumulative_runs']),
                                0)
    
    df['required_run_rate'] = np.where((df['inning'] == 2) & (df['balls_remaining'] > 0),
                                      (df['runs_needed'] * 6) / df['balls_remaining'],
                                      0)
    
    df['runs_ahead'] = np.where(df['inning'] == 2,
                               df['cumulative_runs'] - df['first_innings_total'],
                               0)
    
    # 4. Resource features (simplified DLS)
    print("Step 4: Resource features...")
    total_balls = total_overs * 6
    df['resources_used'] = (df['balls_bowled'] * (10 - df['wickets_remaining'])) / (total_balls * 10)
    df['resources_remaining'] = 1 - df['resources_used']
    
    # 5. Phase of match
    print("Step 5: Phase features...")
    conditions = [
        (df['over'] < 6),
        (df['over'] < 15),
        (df['over'] >= 15)
    ]
    choices = ['powerplay', 'middle', 'death']
    df['phase'] = np.select(conditions, choices, default='middle')
    df['is_powerplay'] = (df['phase'] == 'powerplay').astype(int)
    df['is_death'] = (df['phase'] == 'death').astype(int)
    
    # 6. Recent performance (last 5 overs/30 balls)
    print("Step 6: Momentum features...")
    # This is computationally intensive, so we'll do a simplified version
    df['runs_last_5_overs'] = 0
    df['wickets_last_5_overs'] = 0
    
    for match_id in df['match_id'].unique():
        for inning in [1, 2]:
            mask = (df['match_id'] == match_id) & (df['inning'] == inning)
            inning_df = df[mask].copy()
            
            if len(inning_df) > 0:
                # Rolling sum for last 30 balls (5 overs)
                runs_rolling = inning_df['total_runs'].rolling(window=30, min_periods=1).sum()
                wickets_rolling = inning_df['is_wicket'].rolling(window=30, min_periods=1).sum()
                
                df.loc[mask, 'runs_last_5_overs'] = runs_rolling.values
                df.loc[mask, 'wickets_last_5_overs'] = wickets_rolling.values
    
    df['rr_last_5_overs'] = df['runs_last_5_overs'] / 5
    
    # 7. Partnership features
    print("Step 7: Partnership features...")
    df['partnership_runs'] = df.groupby(['match_id', 'inning']).apply(
        lambda x: x['cumulative_runs'] - x['cumulative_runs'].where(x['cumulative_wickets'] > x['cumulative_wickets'].shift()).ffill()
    ).reset_index(level=[0,1], drop=True).fillna(df['cumulative_runs'])
    
    # 8. Advanced metrics
    print("Step 8: Advanced metrics...")
    df['pressure_index'] = df['cumulative_wickets'] * df['required_run_rate'] / 10
    df['rr_ratio'] = np.where(df['required_run_rate'] > 0,
                             df['current_run_rate'] / df['required_run_rate'],
                             1)
    df['win_prob_simple'] = 1 / (1 + np.exp(-df['runs_ahead'] / 20))
    
    print("Feature engineering completed!")
    return df


def prepare_model_datasets(df_features, match_summary):
    """
    Prepare datasets for modeling
    """
    print("Preparing model datasets...")
    
    # 1. Merge with match outcomes
    df = df_features.merge(
        match_summary[['match_id', 'winner', 'team1', 'team2']],
        on='match_id',
        how='left'
    )
    
    # 2. Create target variable for second innings
    df['batting_team_won'] = 0
    
    # For second innings only
    second_innings_mask = df['inning'] == 2
    df.loc[second_innings_mask, 'batting_team_won'] = (
        df.loc[second_innings_mask, 'batting_team'] == 
        df.loc[second_innings_mask, 'winner']
    ).astype(int)
    
    # 3. Split into first and second innings datasets
    first_innings_df = df[df['inning'] == 1].copy()
    second_innings_df = df[df['inning'] == 2].copy()
    
    # 4. For first innings, add final total as target
    first_innings_totals = first_innings_df.groupby('match_id')['cumulative_runs'].last().reset_index()
    first_innings_totals.columns = ['match_id', 'final_total']
    first_innings_df = first_innings_df.merge(first_innings_totals, on='match_id')
    
    # 5. Filter valid second innings (with targets)
    second_innings_df = second_innings_df[second_innings_df['target'] > 0]
    
    print(f"First innings samples: {len(first_innings_df)}")
    print(f"Second innings samples: {len(second_innings_df)}")
    print(f"Second innings win rate: {second_innings_df['batting_team_won'].mean():.2%}")
    
    return first_innings_df, second_innings_df


def get_important_features():
    """
    Return list of important features for modeling
    """
    basic_features = [
        'over', 'ball', 'overs_completed',
        'balls_remaining', 'wickets_remaining',
        'cumulative_runs', 'cumulative_wickets',
        'current_run_rate'
    ]
    
    chasing_features = [
        'target', 'runs_needed', 'required_run_rate',
        'runs_ahead', 'first_innings_total'
    ]
    
    resource_features = [
        'resources_remaining', 'resources_used'
    ]
    
    phase_features = [
        'phase', 'is_powerplay', 'is_death'
    ]
    
    momentum_features = [
        'runs_last_5_overs', 'wickets_last_5_overs',
        'rr_last_5_overs'
    ]
    
    partnership_features = [
        'partnership_runs'
    ]
    
    advanced_features = [
        'pressure_index', 'rr_ratio', 'win_prob_simple'
    ]
    
    all_features = (basic_features + chasing_features + resource_features + 
                   phase_features + momentum_features + partnership_features + 
                   advanced_features)
    
    return all_features