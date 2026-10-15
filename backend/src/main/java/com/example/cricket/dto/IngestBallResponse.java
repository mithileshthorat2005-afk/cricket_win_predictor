package com.example.cricket.dto;

/**
 * Response to POST /api/matches/{id}/balls.
 * duplicate=true means the eventId had already been accepted; nothing was
 * counted twice and the returned state is the current one.
 */
public record IngestBallResponse(boolean duplicate,
                                 Long matchId,
                                 MatchStateResponse state,
                                 PredictionResultResponse prediction,
                                 String predictionError) {
}
