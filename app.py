import streamlit as st
import pandas as pd
import numpy as np
import sys
import os
import joblib

sys.path.append(os.path.dirname(__file__))
from src.win_probability_engine import WinProbabilityEngine

st.set_page_config(page_title="Cricket Win Predictor", layout="wide")
st.title("🏏 Cricket Win Probability Predictor")
st.markdown("Predict final score or win probability using historical batsman quality and recent momentum.")

# Load engine and batsman quality lookup
@st.cache_resource
def load_engine():
    return WinProbabilityEngine()

@st.cache_resource
def load_quality_lookup():
    return joblib.load('models/batsman_quality.pkl')

engine = load_engine()
quality_lookup = load_quality_lookup()
batsman_names = sorted(quality_lookup.keys())

def get_batsman_quality(name):
    return quality_lookup.get(name, 5.0)

st.sidebar.header("Match State")
inning = st.sidebar.selectbox("Innings", [1, 2], index=0)

# Helper to create batsman selection UI with "New Player" option
def batsman_selector(prefix, default_runs=40, default_balls=30, default_quality=7):
    col1, col2 = st.columns(2)
    with col1:
        options = ["➕ New Player..."] + batsman_names
        selection = st.selectbox("Select player", options, key=f"{prefix}_select")
        if selection == "➕ New Player...":
            name = st.text_input("Enter player name", key=f"{prefix}_name", placeholder="e.g., New Batsman")
            quality = st.slider("Set quality (1-10)", 1, 10, default_quality, key=f"{prefix}_quality")
            st.caption(f"Manual quality: {quality}/10")
        else:
            name = selection
            quality = get_batsman_quality(name)
            st.caption(f"Historical quality: {quality:.1f}/10")
    with col2:
        runs = st.number_input("Runs scored", min_value=0, value=default_runs, key=f"{prefix}_runs")
        balls = st.number_input("Balls faced", min_value=0, value=default_balls, key=f"{prefix}_balls")
    return name, quality, runs, balls

# ---- First Innings ----
if inning == 1:
    st.subheader("First Innings Score Prediction")
    col1, col2 = st.columns(2)
    with col1:
        overs = st.number_input("Overs completed", min_value=0.0, max_value=20.0, step=0.1, value=10.0)
        runs = st.number_input("Runs scored", min_value=0, value=85)
    with col2:
        wickets = st.number_input("Wickets lost", min_value=0, max_value=9, value=3)
        balls_in_over = int((overs % 1) * 10) if overs % 1 != 0 else 0
        over_int = int(overs)
        ball = st.number_input("Ball number", min_value=1, max_value=6, value=balls_in_over+1 if balls_in_over > 0 else 1)

    # Recent momentum
    with st.expander("Recent Momentum (last 10 balls)"):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            runs_last_10 = st.number_input("Runs scored in last 10 balls", min_value=0, value=12, key="first_runs_last_10")
        with col_m2:
            wickets_last_10 = st.number_input("Wickets lost in last 10 balls", min_value=0, max_value=10, value=0, key="first_wickets_last_10")

    # Batsman details
    with st.expander("Batsman Details (from historical performance)"):
        st.markdown("**Striker (on strike)**")
        striker_name, striker_quality, striker_runs, striker_balls = batsman_selector("first_striker", 40, 30, 7)
        st.markdown("**Non‑striker**")
        non_striker_name, non_striker_quality, non_striker_runs, non_striker_balls = batsman_selector("first_non_striker", 20, 20, 5)

    # Map momentum to 5-over features
    runs_last_5_overs = runs_last_10 * 3
    wickets_last_5_overs = wickets_last_10 * 3
    rr_last_5_overs = runs_last_5_overs / 5

    state = {
        'inning': 1,
        'over': over_int,
        'ball': ball,
        'current_runs': runs,
        'current_wickets': wickets,
        'wickets_remaining': 10 - wickets,
        'balls_remaining': (20 - over_int) * 6 - ball + 1,
        'current_run_rate': runs / (over_int + ball/10) if (over_int + ball/10) > 0 else 0,
        'is_powerplay': 1 if over_int < 6 else 0,
        'is_death': 1 if over_int >= 15 else 0,
        'runs_last_5_overs': runs_last_5_overs,
        'wickets_last_5_overs': wickets_last_5_overs,
        'rr_last_5_overs': rr_last_5_overs,
        'partnership_runs': 20,
        'resources_remaining': ((20 - over_int) * 6 - ball + 1) * (10 - wickets) / 1200
    }

    n_sims = st.slider("Number of simulations", min_value=100, max_value=5000, step=100, value=200)

    if st.button("Predict Final Score"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        batch_size = max(1, n_sims // 20)
        all_scores = []
        completed = 0
        for batch_start in range(0, n_sims, batch_size):
            batch_end = min(batch_start + batch_size, n_sims)
            batch_count = batch_end - batch_start
            batch_result = engine.predict_win_probability(
                state, n_simulations=batch_count, progress_callback=None,
                striker_quality=striker_quality, striker_runs=striker_runs, striker_balls=striker_balls,
                non_striker_quality=non_striker_quality, non_striker_runs=non_striker_runs,
                non_striker_balls=non_striker_balls
            )
            all_scores.extend(batch_result['all_scores'])
            completed = batch_end
            progress = completed / n_sims
            progress_bar.progress(progress)
            status_text.text(f"Simulating... {completed}/{n_sims} simulations completed")
        progress_bar.empty()
        status_text.empty()
        predicted = np.mean(all_scores)
        lower = np.percentile(all_scores, 10)
        upper = np.percentile(all_scores, 90)
        st.success(f"**Predicted final score: {predicted:.0f}**")
        st.info(f"90% confidence interval: {lower:.0f} – {upper:.0f}")
        st.metric("Current score", f"{runs}/{wickets}")
        st.metric("Overs completed", f"{overs:.1f}")
        st.metric("Last 10 balls momentum", f"{runs_last_10} runs / {wickets_last_10} wickets")

# ---- Second Innings ----
else:
    st.subheader("Second Innings Win Probability")
    col1, col2, col3 = st.columns(3)
    with col1:
        overs = st.number_input("Overs completed", min_value=0.0, max_value=20.0, step=0.1, value=15.0)
        runs = st.number_input("Runs scored", min_value=0, value=120)
    with col2:
        wickets = st.number_input("Wickets lost", min_value=0, max_value=9, value=4)
        target = st.number_input("Target", min_value=1, value=162)
    with col3:
        over_int = int(overs)
        ball = st.number_input("Ball number", min_value=1, max_value=6, value=1)
        balls_remaining = (20 - over_int) * 6 - ball + 1
        st.metric("Balls remaining", balls_remaining)
        runs_needed = target - runs
        st.metric("Runs needed", runs_needed)
        if balls_remaining > 0:
            req_rr = runs_needed * 6 / balls_remaining
            st.metric("Required RR", f"{req_rr:.2f}")

    # Recent momentum
    with st.expander("Recent Momentum (last 10 balls)"):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            runs_last_10 = st.number_input("Runs scored in last 10 balls", min_value=0, value=15, key="second_runs_last_10")
        with col_m2:
            wickets_last_10 = st.number_input("Wickets lost in last 10 balls", min_value=0, max_value=10, value=0, key="second_wickets_last_10")

    # Batsman details
    with st.expander("Batsman Details (from historical performance)"):
        st.markdown("**Striker (on strike)**")
        striker_name, striker_quality, striker_runs, striker_balls = batsman_selector("second_striker", 40, 30, 7)
        st.markdown("**Non‑striker**")
        non_striker_name, non_striker_quality, non_striker_runs, non_striker_balls = batsman_selector("second_non_striker", 20, 20, 5)

    # Map momentum
    runs_last_5_overs = runs_last_10 * 3
    wickets_last_5_overs = wickets_last_10 * 3
    rr_last_5_overs = runs_last_5_overs / 5

    state = {
        'inning': 2,
        'over': over_int,
        'ball': ball,
        'current_runs': runs,
        'current_wickets': wickets,
        'target': target,
        'balls_remaining': balls_remaining,
        'runs_needed': runs_needed,
        'current_run_rate': runs / (overs + ball/10) if (overs + ball/10) > 0 else 0,
        'is_powerplay': 1 if over_int < 6 else 0,
        'is_death': 1 if over_int >= 15 else 0,
        'runs_last_5_overs': runs_last_5_overs,
        'wickets_last_5_overs': wickets_last_5_overs,
        'rr_last_5_overs': rr_last_5_overs,
        'partnership_runs': 20,
        'resources_remaining': balls_remaining * (10 - wickets) / 1200
    }

    n_sims = st.slider("Number of simulations", min_value=100, max_value=5000, step=100, value=200)

    if st.button("Calculate Win Probability"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        batch_size = max(1, n_sims // 20)
        wins = 0
        completed = 0
        for batch_start in range(0, n_sims, batch_size):
            batch_end = min(batch_start + batch_size, n_sims)
            batch_count = batch_end - batch_start
            batch_result = engine.predict_win_probability(
                state, n_simulations=batch_count, progress_callback=None,
                striker_quality=striker_quality, striker_runs=striker_runs, striker_balls=striker_balls,
                non_striker_quality=non_striker_quality, non_striker_runs=non_striker_runs,
                non_striker_balls=non_striker_balls
            )
            wins += batch_result['win_probability'] * batch_count
            completed = batch_end
            progress = completed / n_sims
            progress_bar.progress(progress)
            status_text.text(f"Simulating... {completed}/{n_sims} simulations completed")
        progress_bar.empty()
        status_text.empty()
        win_prob = wins / n_sims
        st.success(f"**Win Probability: {win_prob:.1%}**")
        st.progress(win_prob)
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Current Score", f"{runs}/{wickets}")
            if balls_remaining > 0:
                st.metric("Required Rate", f"{req_rr:.2f}")
        with col2:
            st.metric("Target", target)
            st.metric("Runs Needed", runs_needed)
        st.metric("Last 10 balls momentum", f"{runs_last_10} runs / {wickets_last_10} wickets")

st.sidebar.markdown("---")
st.sidebar.info("This predictor uses ML + Monte Carlo simulation with **historical batsman quality** (or manual for new players) and recent momentum (last 10 balls).")