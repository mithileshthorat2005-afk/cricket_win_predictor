"""
Win Probability Engine with Monte Carlo Simulation and Batsman Quality Adjustment
Supports both first innings (score prediction) and second innings (win probability).
"""

import pandas as pd
import numpy as np
import joblib
from functools import lru_cache

class WinProbabilityEngine:
    def __init__(self, first_model_path=None, ball_model_path=None):
        if first_model_path is None:
            first_model_path = 'models/first_innings/lightgbm_model.pkl'
        if ball_model_path is None:
            ball_model_path = 'models/ball_outcome/random_forest_model.pkl'

        self.first_model = joblib.load(first_model_path)
        self.first_features = joblib.load(first_model_path.replace('lightgbm_model.pkl', 'feature_columns.pkl'))

        self.ball_model = joblib.load(ball_model_path)
        self.ball_features = joblib.load(ball_model_path.replace('random_forest_model.pkl', 'feature_columns.pkl'))

        self.outcome_names = ['Dot', 'Single', 'Double', 'Triple', 'Four', 'Six', 'Wicket']
        self.default_probs = {
            'powerplay': [0.30, 0.25, 0.15, 0.02, 0.20, 0.05, 0.03],
            'middle': [0.25, 0.30, 0.15, 0.01, 0.20, 0.06, 0.03],
            'death': [0.20, 0.25, 0.10, 0.01, 0.25, 0.15, 0.04]
        }

    # ----- Cached ball outcome probabilities -----
    @lru_cache(maxsize=20000)
    def _get_cached_probs(self, over, ball, runs, wickets, balls_remaining, target,
                          current_run_rate, is_powerplay, is_death, runs_needed):
        ball_state = {
            'over': over,
            'ball': ball,
            'cumulative_runs': runs,
            'cumulative_wickets': wickets,
            'current_run_rate': current_run_rate,
            'is_powerplay': is_powerplay,
            'is_death': is_death,
            'runs_needed': runs_needed
        }
        for feat in self.ball_features:
            if feat not in ball_state:
                if feat == 'balls_remaining':
                    ball_state[feat] = balls_remaining
                elif feat == 'wickets_remaining':
                    ball_state[feat] = 10 - wickets
                elif feat == 'required_run_rate':
                    ball_state[feat] = (runs_needed * 6) / max(balls_remaining, 1)
                elif feat == 'runs_ahead':
                    ball_state[feat] = runs - (target - runs_needed) if target else 0
                elif feat == 'runs_last_5_overs':
                    ball_state[feat] = 30
                elif feat == 'wickets_last_5_overs':
                    ball_state[feat] = 1
                elif feat == 'partnership_runs':
                    ball_state[feat] = 20
                elif feat == 'resources_remaining':
                    ball_state[feat] = (balls_remaining * (10 - wickets)) / 1200
                elif feat == 'pressure_index':
                    req_rr = (runs_needed * 6) / max(balls_remaining, 1)
                    ball_state[feat] = wickets * req_rr / 10
                elif feat == 'rr_ratio':
                    ball_state[feat] = current_run_rate / max((runs_needed * 6) / max(balls_remaining, 1), 0.01)
                elif feat == 'phase_middle':
                    ball_state[feat] = 1 if 6 <= over < 15 else 0
                elif feat == 'phase_powerplay':
                    ball_state[feat] = 1 if over < 6 else 0
                else:
                    ball_state[feat] = 0

        X_ball = pd.DataFrame([ball_state])[self.ball_features]
        try:
            probs = self.ball_model.predict_proba(X_ball)[0]
        except:
            phase = 'powerplay' if over < 6 else ('middle' if over < 15 else 'death')
            probs = self.default_probs[phase]
        return probs

    # ----- Batsman adjustment -----
    @staticmethod
    def adjust_probs_for_batsman(probs, striker_quality, striker_sr, is_powerplay=False):
        quality_factor = (striker_quality - 5) / 10          # -0.4 to +0.5
        sr_factor = (striker_sr - 100) / 200                # -0.5 to +0.5
        total_factor = 1 + quality_factor + sr_factor
        total_factor = max(0.6, min(1.4, total_factor))
        if is_powerplay and striker_quality >= 7:
            total_factor *= 1.1
        run_factor = total_factor
        wicket_factor = 1 / run_factor
        new_probs = probs.copy()
        for i in range(6):
            new_probs[i] *= run_factor
        new_probs[6] *= wicket_factor
        new_probs = new_probs / new_probs.sum()
        return new_probs

    # ----- First innings simulation (with batsman adjustment) -----
    def simulate_first_innings(self, match_state, n_simulations=1000, progress_callback=None,
                               striker_quality=7, striker_runs=0, striker_balls=0,
                               non_striker_quality=5, non_striker_runs=0, non_striker_balls=0):
        current_runs = match_state.get('current_runs', 0)
        current_wickets = match_state.get('current_wickets', 0)
        balls_remaining = match_state.get('balls_remaining', 120)
        over = match_state.get('over', 0)
        ball = match_state.get('ball', 1)
        current_run_rate = match_state.get('current_run_rate',
                                          current_runs / max(over + ball/10, 0.1))

        final_scores = []
        total_sims = n_simulations
        next_report = max(1, total_sims // 20)

        for sim_idx in range(total_sims):
            runs = current_runs
            wickets = current_wickets
            balls = balls_remaining
            ball_idx = 0

            on_strike_quality = striker_quality
            on_strike_runs = striker_runs
            on_strike_balls = striker_balls
            off_strike_quality = non_striker_quality
            off_strike_runs = non_striker_runs
            off_strike_balls = non_striker_balls

            while balls > 0 and wickets < 10:
                current_over = over + (balls_remaining - balls) // 6
                current_ball = ((ball + ball_idx - 1) % 6) + 1
                is_powerplay = 1 if current_over < 6 else 0
                is_death = 1 if current_over >= 15 else 0
                striker_sr = (on_strike_runs / on_strike_balls * 100) if on_strike_balls > 0 else 0

                base_probs = self._get_cached_probs(
                    over=current_over, ball=current_ball,
                    runs=runs, wickets=wickets,
                    balls_remaining=balls, target=None,
                    current_run_rate=current_run_rate,
                    is_powerplay=is_powerplay, is_death=is_death, runs_needed=0
                )
                adj_probs = self.adjust_probs_for_batsman(
                    base_probs, striker_quality=on_strike_quality,
                    striker_sr=striker_sr, is_powerplay=(is_powerplay == 1)
                )
                outcome = np.random.choice(len(adj_probs), p=adj_probs)

                if outcome == 7:
                    wickets += 1
                    on_strike_quality = 3
                    on_strike_runs = 0
                    on_strike_balls = 0
                else:
                    runs += outcome
                    on_strike_runs += outcome
                    on_strike_balls += 1

                if outcome in [1, 3]:
                    (on_strike_quality, off_strike_quality) = (off_strike_quality, on_strike_quality)
                    (on_strike_runs, off_strike_runs) = (off_strike_runs, on_strike_runs)
                    (on_strike_balls, off_strike_balls) = (off_strike_balls, on_strike_balls)

                balls -= 1
                ball_idx += 1

            final_scores.append(runs)

            if progress_callback and (sim_idx + 1) % next_report == 0:
                progress_callback(sim_idx + 1, total_sims)

        if progress_callback:
            progress_callback(total_sims, total_sims)

        return {
            'predicted_score': float(np.mean(final_scores)),
            'confidence_interval': (float(np.percentile(final_scores, 10)),
                                    float(np.percentile(final_scores, 90))),
            'all_scores': final_scores
        }

    # ----- Second innings chase simulation (with batsman adjustment) -----
    def simulate_chase(self, match_state, n_simulations=1000, progress_callback=None,
                       striker_quality=7, striker_runs=0, striker_balls=0,
                       non_striker_quality=5, non_striker_runs=0, non_striker_balls=0):
        current_runs = match_state.get('current_runs', 0)
        current_wickets = match_state.get('current_wickets', 0)
        target = match_state.get('target', 0)
        balls_remaining = match_state.get('balls_remaining', 120)
        over = match_state.get('over', 0)
        ball = match_state.get('ball', 1)
        current_run_rate = match_state.get('current_run_rate',
                                          current_runs / max(over + ball/10, 0.1))

        if target <= 0:
            return 0.0

        wins = 0
        total_sims = n_simulations
        next_report = max(1, total_sims // 20)

        for sim_idx in range(total_sims):
            runs = current_runs
            wickets = current_wickets
            balls = balls_remaining
            ball_idx = 0

            on_strike_quality = striker_quality
            on_strike_runs = striker_runs
            on_strike_balls = striker_balls
            off_strike_quality = non_striker_quality
            off_strike_runs = non_striker_runs
            off_strike_balls = non_striker_balls

            while balls > 0 and wickets < 10:
                current_over = over + (balls_remaining - balls) // 6
                current_ball = ((ball + ball_idx - 1) % 6) + 1
                is_powerplay = 1 if current_over < 6 else 0
                is_death = 1 if current_over >= 15 else 0
                runs_needed = max(0, target - runs)
                striker_sr = (on_strike_runs / on_strike_balls * 100) if on_strike_balls > 0 else 0

                base_probs = self._get_cached_probs(
                    over=current_over, ball=current_ball,
                    runs=runs, wickets=wickets,
                    balls_remaining=balls, target=target,
                    current_run_rate=current_run_rate,
                    is_powerplay=is_powerplay, is_death=is_death, runs_needed=runs_needed
                )
                adj_probs = self.adjust_probs_for_batsman(
                    base_probs, striker_quality=on_strike_quality,
                    striker_sr=striker_sr, is_powerplay=(is_powerplay == 1)
                )
                outcome = np.random.choice(len(adj_probs), p=adj_probs)

                if outcome == 7:
                    wickets += 1
                    on_strike_quality = 3
                    on_strike_runs = 0
                    on_strike_balls = 0
                else:
                    runs += outcome
                    on_strike_runs += outcome
                    on_strike_balls += 1

                if outcome in [1, 3]:
                    (on_strike_quality, off_strike_quality) = (off_strike_quality, on_strike_quality)
                    (on_strike_runs, off_strike_runs) = (off_strike_runs, on_strike_runs)
                    (on_strike_balls, off_strike_balls) = (off_strike_balls, on_strike_balls)

                balls -= 1
                ball_idx += 1

                if runs >= target:
                    break

            if runs >= target:
                wins += 1

            if progress_callback and (sim_idx + 1) % next_report == 0:
                progress_callback(sim_idx + 1, total_sims)

        if progress_callback:
            progress_callback(total_sims, total_sims)

        return wins / total_sims

    # ----- Unified prediction method -----
    def predict_win_probability(self, match_state, n_simulations=1000, progress_callback=None,
                                striker_quality=7, striker_runs=0, striker_balls=0,
                                non_striker_quality=5, non_striker_runs=0, non_striker_balls=0):
        inning = match_state.get('inning', 2)
        if inning == 1:
            return self.simulate_first_innings(
                match_state, n_simulations, progress_callback,
                striker_quality, striker_runs, striker_balls,
                non_striker_quality, non_striker_runs, non_striker_balls
            )
        else:
            win_prob = self.simulate_chase(
                match_state, n_simulations, progress_callback,
                striker_quality, striker_runs, striker_balls,
                non_striker_quality, non_striker_runs, non_striker_balls
            )
            return {'win_probability': win_prob, 'simulations': n_simulations}