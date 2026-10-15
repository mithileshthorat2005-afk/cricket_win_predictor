package com.example.cricket.dto.ws;

/** Accepted ball event published to /topic/match/{matchId}/ball. */
public record BallMessage(Long matchId,
                          String eventId,
                          int inning,
                          int over,
                          int ball,
                          String striker,
                          String bowler,
                          int runs,
                          boolean wicket,
                          long stateVersion) {
}
