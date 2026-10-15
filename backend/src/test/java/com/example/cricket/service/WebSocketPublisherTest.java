package com.example.cricket.service;

import com.example.cricket.model.Delivery;
import com.example.cricket.model.Prediction;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.messaging.simp.SimpMessagingTemplate;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * WebSocket publisher tests: correct topics + stale-result protection
 * (an old, slow prediction must never overwrite a newer one).
 */
class WebSocketPublisherTest {

    private SimpMessagingTemplate template;
    private WebSocketPublisher publisher;

    @BeforeEach
    void setUp() {
        template = mock(SimpMessagingTemplate.class);
        publisher = new WebSocketPublisher(template);
    }

    private static Prediction prediction(long version) {
        return new Prediction(1L, 2, version, "montecarlo", 0.7, 160.0, 1200);
    }

    @Test
    void staleProbability_isDropped_newerIsDelivered() {
        assertTrue(publisher.publishProbability(prediction(5)));
        assertFalse(publisher.publishProbability(prediction(3)), "older version must be dropped");
        assertTrue(publisher.publishProbability(prediction(6)));

        verify(template, times(2)).convertAndSend(eq("/topic/match/1/prob"), any(Object.class));
    }

    @Test
    void sameVersion_isRepublished() {
        assertTrue(publisher.publishProbability(prediction(5)));
        assertTrue(publisher.publishProbability(prediction(5)));
        verify(template, times(2)).convertAndSend(eq("/topic/match/1/prob"), any(Object.class));
    }

    @Test
    void versionsAreTrackedPerMatch() {
        assertTrue(publisher.publishProbability(new Prediction(1L, 2, 3, "montecarlo", 0.7, null, 10)));
        // Match 2 starts fresh - version 1 must not be considered stale
        assertTrue(publisher.publishProbability(new Prediction(2L, 2, 1, "montecarlo", 0.4, null, 10)));
    }

    @Test
    void publishScore_usesMatchTopic() {
        publisher.publishScore(new com.example.cricket.dto.MatchStateResponse(
                7L, 2, "Team B", "Team A", 12.3, 110, 3, 75, 45, 170, 9));
        verify(template).convertAndSend(eq("/topic/match/7/score"), any(Object.class));
    }

    @Test
    void publishBall_usesMatchTopic() {
        publisher.publishBall(7L, 2, new Delivery(7L, null, "evt", 12, 3,
                "Player X", null, "Bowler Y", 4, false, 9));
        verify(template).convertAndSend(eq("/topic/match/7/ball"), any(Object.class));
    }
}
