import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# 1. Load your data
df = pd.read_csv('data/raw/deliveries.csv')  # Adjust filename

# 2. Basic info
print("="*50)
print("DATASET SHAPE:", df.shape)
print("="*50)
print("\nCOLUMNS:")
print(df.columns.tolist())

# 3. Sort the data FIRST
df = df.sort_values(['match_id', 'inning', 'over', 'ball']).reset_index(drop=True)
print("\nData sorted and index reset")

# 4. Handle missing values
print("\nBefore cleaning - missing values:")
print(df.isnull().sum())

df['player_dismissed'] = df['player_dismissed'].fillna('not_out')
df['dismissal_kind'] = df['dismissal_kind'].fillna('not_out')
df['fielder'] = df['fielder'].fillna('none')

# 5. Create basic cumulative features (FIXED VERSION)
print("\nCreating cumulative features...")

# Cumulative runs (simple)
df['cumulative_runs'] = df.groupby(['match_id', 'inning'])['total_runs'].cumsum()

# Cumulative wickets (FIXED)
df['is_wicket'] = (df['player_dismissed'] != 'not_out').astype(int)
df['cumulative_wickets'] = df.groupby(['match_id', 'inning'])['is_wicket'].cumsum()

# Over as float
df['over_float'] = df['over'] + df['ball'] / 10

print("Basic features created successfully!")

# 6. Check match count
print(f"\nTotal unique matches: {df['match_id'].nunique()}")

# 7. Check innings distribution
print(f"\nInnings distribution:")
print(df['inning'].value_counts())

# 8. Create match summary function
def get_match_summary(df):
    match_summaries = []
    
    for match_id in df['match_id'].unique():
        match_df = df[df['match_id'] == match_id]
        
        # Get teams in this match
        batting_teams = match_df['batting_team'].unique()
        if len(batting_teams) < 2:
            continue
            
        # Get innings totals
        innings_totals = []
        for inning in [1, 2]:
            inning_df = match_df[match_df['inning'] == inning]
            if not inning_df.empty:
                # Get last cumulative runs value for the innings total
                total_runs = inning_df['cumulative_runs'].iloc[-1] if len(inning_df) > 0 else 0
                batting_team = inning_df['batting_team'].iloc[0]
                innings_totals.append({
                    'inning': inning,
                    'batting_team': batting_team,
                    'total': total_runs
                })
        
        if len(innings_totals) == 2:
            # Determine winner
            team1 = innings_totals[0]['batting_team']
            team2 = innings_totals[1]['batting_team']
            score1 = innings_totals[0]['total']
            score2 = innings_totals[1]['total']
            
            if score2 > score1:
                winner = team2
                win_by = score2 - score1
                win_type = 'wickets'
            elif score1 > score2:
                winner = team1
                win_by = score1 - score2
                win_type = 'runs'
            else:
                winner = 'Draw'
                win_by = 0
                win_type = 'draw'
            
            match_summaries.append({
                'match_id': match_id,
                'team1': team1,
                'team2': team2,
                'team1_score': score1,
                'team2_score': score2,
                'winner': winner,
                'win_by': win_by,
                'win_type': win_type
            })
    
    return pd.DataFrame(match_summaries)

# Create match summary
print("\nCreating match summaries...")
match_summary = get_match_summary(df)
print(f"Created summary for {len(match_summary)} matches")

# 9. Save the data
print("\nSaving processed data...")
df.to_csv('data/processed/cleaned_data.csv', index=False)
match_summary.to_csv('data/processed/match_summary.csv', index=False)

print("\n" + "="*50)
print("DAY 1 COMPLETED SUCCESSFULLY!")
print("="*50)
print(f"\nFinal dataset shape: {df.shape}")
print(f"Matches processed: {len(match_summary)}")
print("\nNext steps:")
print("1. Analyze match_summary.csv for win distribution")
print("2. Create advanced match-state features")
print("3. Check format (T20/ODI) based on max overs")


# Quick check
print("\n" + "="*50)
print("QUICK DATA CHECK:")
print("="*50)

# Check one match as example
sample_match = df['match_id'].iloc[0]
sample_data = df[df['match_id'] == sample_match]

print(f"\nSample match: {sample_match}")
print(f"Innings: {sample_data['inning'].unique()}")
print(f"Final cumulative runs by inning:")
for inning in [1, 2]:
    inning_data = sample_data[sample_data['inning'] == inning]
    if not inning_data.empty:
        print(f"  Inning {inning}: {inning_data['cumulative_runs'].iloc[-1]} runs, "
              f"{inning_data['cumulative_wickets'].iloc[-1]} wickets")