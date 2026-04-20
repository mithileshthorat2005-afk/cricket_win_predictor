import pandas as pd
import numpy as np
import joblib
import os

print("Loading cleaned data...")
df = pd.read_csv('data/processed/cleaned_data.csv')

# Keep batting deliveries
batting = df[df['batsman_runs'].notna()].copy()

# Group by batsman
batsman_stats = batting.groupby('batsman').agg(
    total_runs=('batsman_runs', 'sum'),
    balls_faced=('ball', 'count'),
    dismissals=('player_dismissed', lambda x: (x != 'not_out').sum())
).reset_index()

# Compute metrics
batsman_stats['strike_rate'] = (batsman_stats['total_runs'] / batsman_stats['balls_faced']) * 100
batsman_stats['batting_avg'] = batsman_stats['total_runs'] / batsman_stats['dismissals'].replace(0, 1)

# Percentile ranks
batsman_stats['sr_percentile'] = batsman_stats['strike_rate'].rank(pct=True)
batsman_stats['avg_percentile'] = batsman_stats['batting_avg'].rank(pct=True)

# Quality score (0-10)
batsman_stats['quality'] = (batsman_stats['sr_percentile'] + batsman_stats['avg_percentile']) / 2 * 10

# Create lookup dict
quality_lookup = dict(zip(batsman_stats['batsman'], batsman_stats['quality']))

# Save to models folder
os.makedirs('models', exist_ok=True)
joblib.dump(quality_lookup, 'models/batsman_quality.pkl')

print(f"✅ Created quality lookup for {len(quality_lookup)} batsmen")
print("\n🏆 Top 10 batsmen by quality:")
print(batsman_stats.nlargest(10, 'quality')[['batsman', 'quality', 'strike_rate', 'batting_avg']].to_string(index=False))