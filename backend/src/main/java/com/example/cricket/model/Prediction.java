package com.example.cricket.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/**
 * A persisted prediction result together with the match-state version it was
 * computed from. Consumers compare stateVersion with the live match version
 * to discard stale (slow, out-of-order) predictions.
 */
@Entity
@Table(name = "predictions",
       indexes = {
               @Index(name = "idx_predictions_match_version", columnList = "match_id, state_version"),
               @Index(name = "idx_predictions_match_created", columnList = "match_id, created_at")
       })
@Getter
@Setter
@NoArgsConstructor
public class Prediction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "match_id", nullable = false)
    private Long matchId;

    @Column(nullable = false)
    private int inning;

    /** Match state version this prediction was computed from. */
    @Column(name = "state_version", nullable = false)
    private long stateVersion;

    /** Which ML path produced this: 'xgboost' or 'montecarlo'. */
    @Column(nullable = false, length = 16)
    private String modelType;

    /** Batting-team win probability. NULL for first-innings montecarlo score
     *  predictions, which produce a score but no probability. */
    @Column
    private Double winProbability;

    /** Predicted final score (montecarlo first-innings only). */
    private Double predictedScore;

    /** Round-trip latency of the FastAPI call, in milliseconds. */
    @Column(nullable = false)
    private long latencyMs;

    @Column(nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    public Prediction(Long matchId, int inning, long stateVersion, String modelType,
                      Double winProbability, Double predictedScore, long latencyMs) {
        this.matchId = matchId;
        this.inning = inning;
        this.stateVersion = stateVersion;
        this.modelType = modelType;
        this.winProbability = winProbability;
        this.predictedScore = predictedScore;
        this.latencyMs = latencyMs;
    }
}
