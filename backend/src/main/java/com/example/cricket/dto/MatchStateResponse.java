package com.example.cricket.dto;

/**
 * Current state of an innings, shaped so it maps 1:1 onto the FastAPI
 * prediction schemas. oversCompleted uses cricket decimal notation
 * (14.3 = 14 overs + 3 balls).
 */
public record MatchStateResponse(Long matchId,
                                 int inning,
                                 String battingTeam,
                                 String bowlingTeam,
                                 double oversCompleted,
                                 int runs,
                                 int wickets,
                                 int ballsBowled,
                                 int ballsRemaining,
                                 Integer target,
                                 long stateVersion) {
}
