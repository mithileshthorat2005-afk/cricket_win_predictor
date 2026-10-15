package com.example.cricket.dto.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/** Mirror of the FastAPI 'PredictionResponse' (POST /predict). */
public record FastApiXgbResponse(
        @JsonProperty("win_probability") double winProbability,
        @JsonProperty("batting_team") String battingTeam,
        @JsonProperty("bowling_team") String bowlingTeam,
        @JsonProperty("inning") int inning,
        @JsonProperty("confidence") String confidence,
        @JsonProperty("key_factors") List<String> keyFactors) {
}
