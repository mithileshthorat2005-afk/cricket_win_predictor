import pandas as pd

# Load your cleaned data
df = pd.read_csv('data/processed/cleaned_data.csv')

# Count unique batsmen
unique_batsmen = df['batsman'].nunique()
print(f"Total unique batsmen in dataset: {unique_batsmen}")

# Optional: Show first few
print("\nSample batsmen:")
print(df['batsman'].unique()[:10])