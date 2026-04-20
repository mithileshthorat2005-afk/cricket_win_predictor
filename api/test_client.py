import requests
import json

# Base URL
BASE_URL = "http://localhost:8000"

# Test health endpoint
def test_health():
    response = requests.get(f"{BASE_URL}/health")
    print("Health check:", response.json())

# Test teams endpoint
def test_teams():
    response = requests.get(f"{BASE_URL}/teams")
    print("Teams:", response.json()[:5])  # Print first 5

# Test prediction
def test_prediction():
    # Example: 1st innings after 15 overs, 120/3
    match_state = {
        "match_id": 1,
        "inning": 1,
        "batting_team": "Mumbai Indians",
        "bowling_team": "Chennai Super Kings",
        "overs_completed": 15.3,
        "runs_scored": 145,
        "wickets_lost": 3,
        "target": None
    }
    
    response = requests.post(
        f"{BASE_URL}/predict",
        json=match_state
    )
    
    print("\nPrediction Result:")
    print(json.dumps(response.json(), indent=2))

# Test 2nd innings prediction
def test_prediction_2nd_innings():
    # Example: 2nd innings chasing 180, after 10 overs 85/2
    match_state = {
        "match_id": 1,
        "inning": 2,
        "batting_team": "Mumbai Indians",
        "bowling_team": "Chennai Super Kings",
        "overs_completed": 10.2,
        "runs_scored": 85,
        "wickets_lost": 2,
        "target": 180
    }
    
    response = requests.post(
        f"{BASE_URL}/predict",
        json=match_state
    )
    
    print("\n2nd Innings Prediction:")
    print(json.dumps(response.json(), indent=2))

if __name__ == "__main__":
    print("Testing Cricket Win Predictor API")
    print("="*50)
    
    test_health()
    test_teams()
    test_prediction()
    test_prediction_2nd_innings()