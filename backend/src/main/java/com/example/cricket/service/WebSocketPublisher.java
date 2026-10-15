package com.example.cricket.service;

import com.example.cricket.dto.MatchStateResponse;
import com.example.cricket.dto.ws.BallMessage;
import com.example.cricket.dto.ws.ProbabilityMessage;
import com.example.cricket.dto.ws.ScoreMessage;
import com.example.cricket.model.Delivery;
import com.example.cricket.model.Prediction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Publishes match updates over STOMP:
 *   /topic/match/{matchId}/score  - accepted ball events (score updates)
 *   /topic/match/{matchId}/prob   - win probabilities
 *   /topic/match/{matchId}/ball   - individual deliveries
 *
 * Stale-result protection: a slow prediction computed from an older match
 * state must never overwrite a newer one. Each match tracks the version of
 * the last PUBLISHED probability; older results are dropped (still stored in
 * MySQL with a stale flag by the caller).
 */
@Component
public class WebSocketPublisher {

    private static final Logger log = LoggerFactory.getLogger(WebSocketPublisher.class);

    private final SimpMessagingTemplate messagingTemplate;
    private final Map<Long, Long> lastPublishedProbVersion = new ConcurrentHashMap<>();

    public WebSocketPublisher(SimpMessagingTemplate messagingTemplate) {
        this.messagingTemplate = messagingTemplate;
    }

    public void publishScore(MatchStateResponse state) {
        messagingTemplate.convertAndSend(
                "/topic/match/" + state.matchId() + "/score",
                new ScoreMessage(state.matchId(), state.inning(), state.battingTeam(),
                        state.runs(), state.wickets(), state.oversCompleted(), state.stateVersion()));
    }

    public void publishBall(Long matchId, int inning, Delivery delivery) {
        messagingTemplate.convertAndSend(
                "/topic/match/" + matchId + "/ball",
                new BallMessage(matchId, delivery.getEventId(), inning,
                        delivery.getOver(), delivery.getBall(),
                        delivery.getStriker(), delivery.getBowler(),
                        delivery.getRuns(), delivery.isWicket(), delivery.getStateVersionAfter()));
    }

    /** Returns false when the probability was dropped as stale. */
    public boolean publishProbability(Prediction prediction) {
        Long last = lastPublishedProbVersion.get(prediction.getMatchId());
        if (last != null && prediction.getStateVersion() < last) {
            log.warn("Dropping stale probability for match {}: predVersion={} < publishedVersion={}",
                    prediction.getMatchId(), prediction.getStateVersion(), last);
            return false;
        }
        lastPublishedProbVersion.put(prediction.getMatchId(), prediction.getStateVersion());
        messagingTemplate.convertAndSend(
                "/topic/match/" + prediction.getMatchId() + "/prob",
                new ProbabilityMessage(prediction.getMatchId(), prediction.getInning(),
                        prediction.getWinProbability(), prediction.getPredictedScore(),
                        prediction.getModelType(), prediction.getStateVersion(),
                        prediction.getLatencyMs()));
        return true;
    }
}
