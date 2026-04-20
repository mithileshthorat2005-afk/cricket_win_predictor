import pandas as pd
import numpy as np
from tqdm import tqdm

class CricketFeatureEngineer:
    def __init__(self, deliveries_df, match_summary_df):
        self.deliveries = deliveries_df
        self.match_summary = match_summary_df
        self.features = None
        
    def create_match_state_features(self):
        """Create features that represent the current match state"""
        df = self.deliveries.copy()
        
        print("Creating match state features...")
        
        # 1. Current Run Rate
        df['current_rr'] = df['cumulative_runs'] / (df['over'] + df['ball']/6)
        
        # 2. Balls remaining in innings
        df['balls_remaining'] = 120 - ((df['over'] - 1) * 6 + df['ball'])  # 120 balls in T20
        
        # 3. Wickets in hand
        df['wickets_in_hand'] = 10 - df['cumulative_wickets']
        
        # 4. Projected score at current rate
        df['projected_score'] = df['current_rr'] * 20
        
        # 5. Partnerships (runs since last wicket)
        df['partnership_runs'] = df.groupby(['match_id', 'inning', 'cumulative_wickets'])['total_runs'].cumsum()
        
        # 6. Balls in current partnership
        df['partnership_balls'] = df.groupby(['match_id', 'inning', 'cumulative_wickets']).cumcount() + 1
        
        # 7. Partnership run rate
        df['partnership_rr'] = df['partnership_runs'] / (df['partnership_balls'] / 6)
        
        # 8. Dot ball percentage in current over
        df['is_dot'] = (df['total_runs'] == 0).astype(int)
        df['over_dot_balls'] = df.groupby(['match_id', 'inning', 'over'])['is_dot'].cumsum()
        df['over_completed_balls'] = df.groupby(['match_id', 'inning', 'over']).cumcount() + 1
        df['over_dot_pct'] = df['over_dot_balls'] / df['over_completed_balls']
        
        # 9. Boundaries in current over
        df['is_boundary'] = (df['batsman_runs'] == 4).astype(int)
        df['is_six'] = (df['batsman_runs'] == 6).astype(int)
        df['over_boundaries'] = df.groupby(['match_id', 'inning', 'over'])['is_boundary'].cumsum()
        df['over_sixes'] = df.groupby(['match_id', 'inning', 'over'])['is_six'].cumsum()
        
        # 10. Momentum (runs in last 5 balls)
        df['last_5_balls_runs'] = df.groupby(['match_id', 'inning'])['total_runs'].transform(
            lambda x: x.rolling(window=5, min_periods=1).sum()
        )
        
        # 11. Wickets in last 10 balls
        df['last_10_balls_wickets'] = df.groupby(['match_id', 'inning'])['is_wicket'].transform(
            lambda x: x.rolling(window=10, min_periods=1).sum()
        )
        
        return df
    
    def add_required_run_rate(self, df):
        """Add required run rate for 2nd innings"""
        print("Adding required run rate for 2nd innings...")
        
        # Merge with match summary to get target
        df = df.merge(
            self.match_summary[['match_id', 'team1', 'team2', 'team1_score']], 
            on='match_id', 
            how='left'
        )
        
        # Determine target for 2nd innings
        df['target'] = np.where(
            df['inning'] == 2,
            np.where(
                df['batting_team'] == df['team2'],
                df['team1_score'] + 1,  # Team2 batting, target is team1_score + 1
                df['team1_score'] + 1    # Team1 batting in 2nd innings? (unusual but handle)
            ),
            np.nan
        )
        
        # Required runs and rate for 2nd innings
        df['runs_required'] = df['target'] - df['cumulative_runs']
        df['required_rr'] = np.where(
            (df['inning'] == 2) & (df['balls_remaining'] > 0),
            df['runs_required'] / (df['balls_remaining'] / 6),
            np.nan
        )
        
        # Required rate relative to current rate
        df['rr_difference'] = df['required_rr'] - df['current_rr']
        
        return df
    
    def create_bowler_features(self, df):
        """Create features about the current bowler"""
        print("Creating bowler-specific features...")
        
        # Bowler's performance in current match so far
        bowler_stats = df.groupby(['match_id', 'inning', 'bowler']).agg({
            'total_runs': 'sum',
            'is_wicket': 'sum',
            'ball': 'count'
        }).rename(columns={
            'total_runs': 'bowler_runs_conceded',
            'is_wicket': 'bowler_wickets',
            'ball': 'bowler_balls'
        }).reset_index()
        
        # Calculate economy
        bowler_stats['bowler_economy'] = bowler_stats['bowler_runs_conceded'] / (bowler_stats['bowler_balls'] / 6)
        
        # Merge back
        df = df.merge(bowler_stats, on=['match_id', 'inning', 'bowler'], how='left')
        
        # Bowler's performance in last 12 balls
        df['bowler_last_12_runs'] = df.groupby(['match_id', 'inning', 'bowler'])['total_runs'].transform(
            lambda x: x.rolling(window=12, min_periods=1).sum()
        )
        
        df['bowler_last_12_wickets'] = df.groupby(['match_id', 'inning', 'bowler'])['is_wicket'].transform(
            lambda x: x.rolling(window=12, min_periods=1).sum()
        )
        
        return df
    
    def create_batsman_features(self, df):
        """Create features about the current batsman"""
        print("Creating batsman-specific features...")
        
        # Batsman's performance in current match so far
        batsman_stats = df.groupby(['match_id', 'inning', 'batsman']).agg({
            'batsman_runs': 'sum',
            'ball': 'count'
        }).rename(columns={
            'batsman_runs': 'batsman_runs_scored',
            'ball': 'batsman_balls_faced'
        }).reset_index()
        
        # Calculate strike rate
        batsman_stats['batsman_sr'] = (batsman_stats['batsman_runs_scored'] / batsman_stats['batsman_balls_faced']) * 100
        
        # Merge back
        df = df.merge(batsman_stats, on=['match_id', 'inning', 'batsman'], how='left')
        
        # Batsman's performance in last 6 balls
        df['batsman_last_6_runs'] = df.groupby(['match_id', 'inning', 'batsman'])['batsman_runs'].transform(
            lambda x: x.rolling(window=6, min_periods=1).sum()
        )
        
        df['batsman_last_6_balls'] = df.groupby(['match_id', 'inning', 'batsman']).cumcount() + 1
        df['batsman_last_6_sr'] = (df['batsman_last_6_runs'] / df['batsman_last_6_balls']) * 100
        
        return df
    
    def create_stage_features(self, df):
        """Create features about the match stage"""
        print("Creating match stage features...")
        
        # Powerplay (overs 1-6)
        df['is_powerplay'] = (df['over'] <= 6).astype(int)
        
        # Middle overs (7-15)
        df['is_middle_overs'] = ((df['over'] >= 7) & (df['over'] <= 15)).astype(int)
        
        # Death overs (16-20)
        df['is_death_overs'] = (df['over'] >= 16).astype(int)
        
        # Time remaining (normalized)
        df['time_remaining'] = df['balls_remaining'] / 120
        
        # Wickets remaining (normalized)
        df['wickets_remaining_norm'] = df['wickets_in_hand'] / 10
        
        return df
    
    def create_all_features(self):
        """Pipeline to create all features"""
        print("="*50)
        print("STARTING ADVANCED FEATURE ENGINEERING")
        print("="*50)
        
        # Step 1: Basic match state
        df = self.create_match_state_features()
        print(f"After match state features: {df.shape}")
        
        # Step 2: Required run rate
        df = self.add_required_run_rate(df)
        print(f"After required RR features: {df.shape}")
        
        # Step 3: Bowler features
        df = self.create_bowler_features(df)
        print(f"After bowler features: {df.shape}")
        
        # Step 4: Batsman features
        df = self.create_batsman_features(df)
        print(f"After batsman features: {df.shape}")
        
        # Step 5: Stage features
        df = self.create_stage_features(df)
        print(f"After stage features: {df.shape}")
        
        self.features = df
        return df
    
    def prepare_modeling_data(self):
        """Prepare final dataset for modeling"""
        print("\nPreparing data for modeling...")
        
        # Select features for modeling
        feature_columns = [
            # Match context
            'inning', 'over', 'ball',
            
            # Run metrics
            'cumulative_runs', 'current_rr', 'projected_score',
            'runs_required', 'required_rr', 'rr_difference',
            
            # Wicket metrics
            'cumulative_wickets', 'wickets_in_hand',
            
            # Time metrics
            'balls_remaining', 'time_remaining', 'wickets_remaining_norm',
            
            # Partnership
            'partnership_runs', 'partnership_balls', 'partnership_rr',
            
            # Over stats
            'over_dot_pct', 'over_boundaries', 'over_sixes',
            
            # Momentum
            'last_5_balls_runs', 'last_10_balls_wickets',
            
            # Bowler stats
            'bowler_economy', 'bowler_last_12_runs', 'bowler_last_12_wickets',
            
            # Batsman stats
            'batsman_sr', 'batsman_last_6_sr',
            
            # Match stage
            'is_powerplay', 'is_middle_overs', 'is_death_overs'
        ]
        
        # Create target variable (1 if batting team wins, 0 otherwise)
        modeling_df = self.features.copy()
        
        # Merge with match summary to get winner
        modeling_df = modeling_df.merge(
            self.match_summary[['match_id', 'winner']], 
            on='match_id', 
            how='left'
        )
        
        # Create target: 1 if batting team wins
        modeling_df['target'] = (modeling_df['batting_team'] == modeling_df['winner']).astype(int)
        
        # For 2nd innings, we need to invert? Actually, target is already correct
        # because batting team in 2nd innings wins if they chase successfully
        
        # Handle NaN values
        modeling_df = modeling_df.fillna(0)
        
        return modeling_df[feature_columns + ['target', 'match_id', 'inning', 'batting_team', 'bowling_team']]

# Usage
if __name__ == "__main__":
    # Load your data
    df = pd.read_csv('data/processed/cleaned_data.csv')
    match_summary = pd.read_csv('data/processed/match_summary.csv')
    
    # Create features
    engineer = CricketFeatureEngineer(df, match_summary)
    df_features = engineer.create_all_features()
    
    # Prepare for modeling
    modeling_data = engineer.prepare_modeling_data()
    
    # Save
    modeling_data.to_csv('data/processed/modeling_data.csv', index=False)
    print(f"\n✅ Modeling data saved with {len(modeling_data)} rows and {modeling_data.shape[1]-3} features")
    print(f"Target distribution:\n{modeling_data['target'].value_counts(normalize=True)}")