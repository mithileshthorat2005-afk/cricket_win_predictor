package com.example.cricket.dto;

import com.example.cricket.model.Match;

import java.time.Instant;

/** Public match representation. */
public record MatchResponse(Long id, String team1, String team2, String status,
                            int currentInnings, long stateVersion, Instant createdAt) {

    public static MatchResponse from(Match m) {
        return new MatchResponse(m.getId(), m.getTeam1(), m.getTeam2(), m.getStatus(),
                m.getCurrentInnings(), m.getStateVersion(), m.getCreatedAt());
    }
}
