package com.example.cricket.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/**
 * A single accepted ball event.
 * eventId provides idempotency: a (match_id, event_id) pair can only ever be
 * counted once, so retried deliveries are safely ignored.
 */
@Entity
@Table(name = "deliveries",
       uniqueConstraints = @UniqueConstraint(name = "uq_deliveries_match_event",
                                             columnNames = {"match_id", "event_id"}),
       indexes = @Index(name = "idx_deliveries_match_innings", columnList = "match_id, innings_id"))
@Getter
@Setter
@NoArgsConstructor
public class Delivery {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "match_id", nullable = false)
    private Long matchId;

    @Column(name = "innings_id", nullable = false)
    private Long inningsId;

    /** Client-supplied idempotency key (e.g. "1234:2:15:3"). */
    @Column(name = "event_id", nullable = false, length = 64)
    private String eventId;

    // 'over' is a reserved word in MySQL 8 (window functions) => over_number
    @Column(name = "over_number", nullable = false)
    private int over;

    @Column(nullable = false)
    private int ball;

    @Column(nullable = false, length = 64)
    private String striker;

    @Column(length = 64)
    private String nonStriker;

    @Column(nullable = false, length = 64)
    private String bowler;

    @Column(nullable = false)
    private int runs;

    @Column(nullable = false)
    private boolean wicket;

    /** Match state version AFTER this delivery was applied. */
    @Column(nullable = false)
    private long stateVersionAfter;

    @Column(nullable = false, updatable = false)
    private Instant createdAt = Instant.now();

    public Delivery(Long matchId, Long inningsId, String eventId, int over, int ball,
                    String striker, String nonStriker, String bowler,
                    int runs, boolean wicket, long stateVersionAfter) {
        this.matchId = matchId;
        this.inningsId = inningsId;
        this.eventId = eventId;
        this.over = over;
        this.ball = ball;
        this.striker = striker;
        this.nonStriker = nonStriker;
        this.bowler = bowler;
        this.runs = runs;
        this.wicket = wicket;
        this.stateVersionAfter = stateVersionAfter;
    }
}
