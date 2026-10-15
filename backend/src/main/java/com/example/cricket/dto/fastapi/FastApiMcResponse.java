package com.example.cricket.dto.fastapi;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Mirror of the FastAPI 'MonteCarloResponse' (POST /predict/montecarlo).
 * inning=1 => predictedScore + confidenceInterval, winProbability null.
 * inning=2 => winProbability, predictedScore null.
 */
public record FastApiMcResponse(
        @JsonProperty("inning") int inning,
        @JsonProperty("win_probability") Double winProbability,
        @JsonProperty("predicted_score") Double predictedScore,
        @JsonProperty("confidence_interval") List<Double> confidenceInterval,
        @JsonProperty("simulations") int simulations,
        @JsonProperty("note") String note) {
}
