package com.example.cricket.model;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * One innings of a match. Running totals are updated as ball events arrive.
 */
@Entity
@Table(name = "innings",
       uniqueConstraints = @UniqueConstraint(name = "uq_innings_match_inning",
                                             columnNames = {"match_id", "inning_number"}))
@Getter
@Setter
@NoArgsConstructor
public class Innings {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "match_id", nullable = false)
    private Long matchId;

    @Column(name = "inning_number", nullable = false)
    private int inningNumber;

    @Column(nullable = false)
    private String battingTeam;

    @Column(nullable = false)
    private String bowlingTeam;

    @Column(nullable = false)
    private int runs;

    @Column(nullable = false)
    private int wickets;

    /** Legal balls bowled in this innings (12 = 2.0 overs). */
    @Column(nullable = false)
    private int ballsBowled;

    /** Target for the chasing innings (innings 2 only). */
    private Integer target;

    @Column(nullable = false)
    private boolean completed;

    public Innings(Long matchId, int inningNumber, String battingTeam, String bowlingTeam, Integer target) {
        this.matchId = matchId;
        this.inningNumber = inningNumber;
        this.battingTeam = battingTeam;
        this.bowlingTeam = bowlingTeam;
        this.target = target;
    }
}
