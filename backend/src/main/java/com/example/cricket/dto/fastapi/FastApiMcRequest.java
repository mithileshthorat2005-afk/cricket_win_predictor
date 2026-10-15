package com.example.cricket.dto.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Mirror of the FastAPI pydantic model 'MonteCarloRequest' (POST /predict/montecarlo).
 * Batsman 'quality' is optional when 'name' exists in the 516-player database.
 */
public record FastApiMcRequest(
        @JsonProperty("match_id") Integer matchId,
        @JsonProperty("inning") int inning,
        @JsonProperty("over") int over,
        @JsonProperty("ball") int ball,
        @JsonProperty("current_runs") int currentRuns,
        @JsonProperty("current_wickets") int currentWickets,
        @JsonProperty("target") Integer target,
        @JsonProperty("n_simulations") int nSimulations,
        @JsonProperty("striker") Batsman striker,
        @JsonProperty("non_striker") Batsman nonStriker) {

    public record Batsman(
            @JsonProperty("name") String name,
            @JsonProperty("quality") Double quality,
            @JsonProperty("runs") int runs,
            @JsonProperty("balls") int balls) {
    }
}
