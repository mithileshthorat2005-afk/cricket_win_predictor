package com.example.cricket.dto.ws;

/** Score update published to /topic/match/{matchId}/score. */
public record ScoreMessage(Long matchId,
                           int inning,
                           String battingTeam,
                           int runs,
                           int wickets,
                           double oversCompleted,
                           long stateVersion) {
}
