package com.example.cricket.dto.ws;

/** Win-probability update published to /topic/match/{matchId}/prob. */
public record ProbabilityMessage(Long matchId,
                                 int inning,
                                 Double winProbability,
                                 Double predictedScore,
                                 String modelType,
                                 long stateVersion,
                                 long latencyMs) {
}
