package com.example.cricket.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/**
 * A cricket match managed by the orchestrator.
 * stateVersion increments on every accepted ball event; predictions and
 * WebSocket payloads carry the version so stale results can be discarded.
 */
@Entity
@Table(name = "matches", indexes = {
        @Index(name = "idx_matches_status", columnList = "status")
})
@Getter
@Setter
@NoArgsConstructor
public class Match {

    public static final String STATUS_LIVE = "LIVE";
    public static final String STATUS_COMPLETED = "COMPLETED";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String team1;

    @Column(nullable = false)
    private String team2;

    @Column(nullable = false, length = 32)
    private String status = STATUS_LIVE;

    /** Innings the match is currently in (1 or 2). */
    @Column(nullable = false)
    private int currentInnings = 1;

    /** Monotonic match-state version, bumped per accepted ball event. */
    @Column(nullable = false)
    private long stateVersion = 0;

    @Column(nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    @Column(nullable = false)
    private Instant updatedAt = Instant.now();

    public Match(String team1, String team2) {
        this.team1 = team1;
        this.team2 = team2;
    }
}
