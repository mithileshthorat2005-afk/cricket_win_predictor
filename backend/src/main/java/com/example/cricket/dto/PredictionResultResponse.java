package com.example.cricket.dto;

import java.time.Instant;

/**
 * A stored prediction, flagged stale when the match has moved on since the
 * prediction was computed (stateVersion < live match stateVersion).
 */
public record PredictionResultResponse(Long id,
                                       Long matchId,
                                       int inning,
                                       long stateVersion,
                                       String modelType,
                                       Double winProbability,
                                       Double predictedScore,
                                       long latencyMs,
                                       Instant createdAt,
                                       boolean stale) {
}
