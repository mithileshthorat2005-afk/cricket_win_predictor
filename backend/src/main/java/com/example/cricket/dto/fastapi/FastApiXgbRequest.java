package com.example.cricket.dto.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Mirror of the FastAPI pydantic model 'MatchState' (POST /predict).
 * Contract documented in README.api.md - keep in sync with api/app.py.
 */
public record FastApiXgbRequest(
        @JsonProperty("match_id") int matchId,
        @JsonProperty("inning") int inning,
        @JsonProperty("batting_team") String battingTeam,
        @JsonProperty("bowling_team") String bowlingTeam,
        @JsonProperty("overs_completed") double oversCompleted,
        @JsonProperty("runs_scored") int runsScored,
        @JsonProperty("wickets_lost") int wicketsLost,
        @JsonProperty("target") Integer target) {
}
