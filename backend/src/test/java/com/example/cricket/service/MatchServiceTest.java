package com.example.cricket.service;

import com.example.cricket.dto.BallEventRequest;
import com.example.cricket.dto.CreateMatchRequest;
import com.example.cricket.dto.MatchStateResponse;
import com.example.cricket.exception.InvalidMatchStateException;
import com.example.cricket.exception.MatchNotFoundException;
import com.example.cricket.model.Delivery;
import com.example.cricket.model.Match;
import com.example.cricket.repository.DeliveryRepository;
import com.example.cricket.repository.InningsRepository;
import com.example.cricket.repository.MatchRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Match lifecycle + ball ingestion against real H2 (schema via Flyway).
 * Covers idempotency, state computation and innings progression.
 */
@SpringBootTest
@ActiveProfiles("test")
class MatchServiceTest {

    @Autowired private MatchService matchService;
    @Autowired private MatchRepository matchRepository;
    @Autowired private InningsRepository inningsRepository;
    @Autowired private DeliveryRepository deliveryRepository;

    private Long newMatch() {
        return matchService.createMatch(new CreateMatchRequest("Team A", "Team B")).id();
    }

    private static BallEventRequest ball(int over, int ball, int runs, boolean wicket) {
        return new BallEventRequest(null, 1, over, ball, "Player X", null, "Bowler Y", runs, wicket);
    }

    @Test
    void createMatch_opensFirstInnings() {
        Long id = newMatch();
        var state = matchService.getState(id);
        assertEquals(1, state.inning());
        assertEquals("Team A", state.battingTeam());
        assertEquals(0, state.runs());
        assertEquals(0, state.stateVersion());
    }

    @Test
    void createMatch_sameTeam_rejected() {
        assertThrows(InvalidMatchStateException.class,
                () -> matchService.createMatch(new CreateMatchRequest("Team A", "team a")));
    }

    @Test
    void getMatch_unknown_404() {
        assertThrows(MatchNotFoundException.class, () -> matchService.getMatch(999999L));
    }

    @Test
    void ingestBall_updatesStateAndVersion() {
        Long id = newMatch();
        matchService.ingestBall(id, ball(0, 1, 4, false));
        matchService.ingestBall(id, ball(0, 2, 1, true));
        MatchStateResponse state = matchService.getState(id);

        assertEquals(5, state.runs());
        assertEquals(1, state.wickets());
        assertEquals(2, state.ballsBowled());
        assertEquals(0.2, state.oversCompleted(), 1e-9);
        assertEquals(2, state.stateVersion()); // one bump per accepted ball
    }

    @Test
    void duplicateEvent_isNotCountedTwice() {
        Long id = newMatch();
        long deliveriesBefore = deliveryRepository.count();
        var first = new BallEventRequest("evt-1", 1, 0, 1, "Player X", null, "Bowler Y", 6, false);
        var retry = new BallEventRequest("evt-1", 1, 0, 1, "Player X", null, "Bowler Y", 6, false);

        var r1 = matchService.ingestBall(id, first);
        assertFalse(r1.duplicate());

        var r2 = matchService.ingestBall(id, retry);
        assertTrue(r2.duplicate());

        var state = matchService.getState(id);
        assertEquals(6, state.runs(), "retry must not add runs again");
        assertEquals(1, state.stateVersion(), "retry must not bump the version");
        // H2 DB is shared across tests: assert only ONE new delivery row
        assertEquals(deliveriesBefore + 1, deliveryRepository.count());
    }

    @Test
    void duplicateDerivedEvent_sameInningOverBall_deduplicated() {
        Long id = newMatch();
        // No explicit eventId -> derived from (match, inning, over, ball)
        var r1 = matchService.ingestBall(id, ball(0, 3, 1, false));
        var r2 = matchService.ingestBall(id, ball(0, 3, 1, false));
        assertFalse(r1.duplicate());
        assertTrue(r2.duplicate());
        assertEquals(1, matchService.getState(id).ballsBowled());
    }

    @Test
    void secondInnings_rejectedBeforeFirstCompletes() {
        Long id = newMatch();
        var event = new BallEventRequest(null, 2, 0, 1, "Player X", null, "Bowler Y", 1, false);
        assertThrows(InvalidMatchStateException.class, () -> matchService.ingestBall(id, event));
    }

    @Test
    void tenWickets_endInningsAndOpenChaseWithTarget() {
        Long id = newMatch();
        for (int i = 0; i < 10; i++) {
            matchService.ingestBall(id, ball(i, 1, 1, true)); // 10 runs, 10 wickets
        }
        var match = matchRepository.findById(id).orElseThrow();
        assertEquals(2, match.getCurrentInnings(), "innings 1 should be complete");

        var second = new BallEventRequest(null, 2, 0, 1, "Player Z", null, "Bowler W", 2, false);
        matchService.ingestBall(id, second);
        var chase = inningsRepository.findByMatchIdAndInningNumber(id, 2).orElseThrow();
        assertEquals(11, chase.getTarget(), "target = first-innings total + 1");
        assertEquals("Team B", chase.getBattingTeam());
    }

    @Test
    void completedChase_marksMatchCompleted_andRejectsFurtherBalls() {
        Long id = newMatch();
        for (int i = 0; i < 10; i++) {
            matchService.ingestBall(id, ball(i, 1, 1, true)); // Team A: 10 all out (10 runs)
        }
        // Team B chases 11: two sixes (12 runs) win the match
        matchService.ingestBall(id, new BallEventRequest(null, 2, 0, 1, "Player Z", null, "Bowler W", 6, false));
        matchService.ingestBall(id, new BallEventRequest(null, 2, 0, 2, "Player Z", null, "Bowler W", 6, false));

        assertEquals(Match.STATUS_COMPLETED, matchRepository.findById(id).orElseThrow().getStatus());

        var afterEnd = new BallEventRequest(null, 2, 0, 3, "Player Z", null, "Bowler W", 1, false);
        assertThrows(InvalidMatchStateException.class, () -> matchService.ingestBall(id, afterEnd));
    }

    @Test
    void oversConversion_matchesCricketNotation() {
        assertEquals(0.0, MatchService.toOvers(0), 1e-9);
        assertEquals(6.0, MatchService.toOvers(36), 1e-9);
        assertEquals(6.3, MatchService.toOvers(39), 1e-9);
        assertEquals(19.5, MatchService.toOvers(119), 1e-9);
    }

    @Test
    void deliveriesPersistedWithStateVersionAfter() {
        Long id = newMatch();
        matchService.ingestBall(id, ball(0, 1, 2, false));
        Delivery d = deliveryRepository.findByMatchIdAndEventId(id, "m" + id + ":i1:o0:b1").orElseThrow();
        assertEquals(1, d.getStateVersionAfter(), "first ball -> version 1");
        assertEquals(2, d.getRuns());
    }
}
