package com.example.cricket.websocket;

import com.example.cricket.client.FastApiClient;
import com.example.cricket.dto.fastapi.FastApiXgbRequest;
import com.example.cricket.dto.fastapi.FastApiXgbResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.messaging.converter.SimpleMessageConverter;
import org.springframework.messaging.simp.stomp.StompFrameHandler;
import org.springframework.messaging.simp.stomp.StompHeaders;
import org.springframework.messaging.simp.stomp.StompSession;
import org.springframework.messaging.simp.stomp.StompSessionHandlerAdapter;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.messaging.WebSocketStompClient;
import org.springframework.web.socket.sockjs.client.SockJsClient;
import org.springframework.web.socket.sockjs.client.WebSocketTransport;

import java.lang.reflect.Type;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * End-to-end STOMP test: a real SockJS/STOMP client connects to the running
 * app, subscribes to /topic/match/{id}/score and /prob; a ball is then
 * ingested through the REST API and the broadcasts must arrive on both
 * topics. A second subscriber on the same match receives the message too.
 *
 * The client uses SimpleMessageConverter and parses the raw payload bytes
 * itself (a Jackson converter asking for String.class would fail on a JSON
 * object payload and fail silently).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
class StompIntegrationTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    @LocalServerPort private int port;
    @Autowired private TestRestTemplate rest;
    @MockitoBean private FastApiClient fastApiClient;

    private WebSocketStompClient stompClient;
    private StompSession session;
    private final BlockingQueue<Map<String, Object>> scoreMessages = new LinkedBlockingQueue<>();
    private final BlockingQueue<Map<String, Object>> probMessages = new LinkedBlockingQueue<>();

    @BeforeEach
    void connectAndSubscribe() throws Exception {
        stompClient = new WebSocketStompClient(new SockJsClient(
                List.of(new WebSocketTransport(new StandardWebSocketClient()))));
        stompClient.setMessageConverter(new SimpleMessageConverter());

        session = stompClient
                .connect("ws://localhost:" + port + "/ws", new StompSessionHandlerAdapter() {})
                .get(10, TimeUnit.SECONDS);
        assertTrue(session.isConnected());

        String matchId = createMatch();
        session.subscribe("/topic/match/" + matchId + "/score", handler(scoreMessages));
        session.subscribe("/topic/match/" + matchId + "/prob", handler(probMessages));
        Thread.sleep(500); // let subscriptions register with the broker

        when(fastApiClient.predictXgb(any(FastApiXgbRequest.class))).thenReturn(
                new FastApiXgbResponse(0.66, "Team A", "Team B", 1, "Medium", List.of("factor")));
    }

    @AfterEach
    void tearDown() {
        if (session != null && session.isConnected()) session.disconnect();
    }

    @Test
    void ballIngestion_broadcastsScore_thenPredictionBroadcastsProbability() throws Exception {
        String matchId = currentMatchId();

        // 1. Ingest a ball (auto-predict off in test profile) -> score broadcast
        rest.postForObject(base() + "/api/matches/" + matchId + "/balls",
                ball(0, 1, 4, false), Map.class);

        Map<String, Object> score = scoreMessages.poll(15, TimeUnit.SECONDS);
        assertNotNull(score, "score broadcast must arrive after an accepted ball");
        assertEquals(4, ((Number) score.get("runs")).intValue(), "payload must contain new runs");
        assertEquals(1, ((Number) score.get("stateVersion")).intValue(), "payload must carry stateVersion");

        // 2. Explicit prediction -> prob broadcast
        rest.postForObject(base() + "/api/matches/" + matchId + "/predict",
                Map.of("model", "xgboost"), Map.class);

        Map<String, Object> prob = probMessages.poll(15, TimeUnit.SECONDS);
        assertNotNull(prob, "probability broadcast must arrive after a successful prediction");
        assertEquals(0.66, ((Number) prob.get("winProbability")).doubleValue(), 1e-9);
        assertEquals("xgboost", prob.get("modelType"), "payload must name the model");
    }

    @Test
    void multipleSubscribers_onSameMatch_bothReceiveTheScore() throws Exception {
        BlockingQueue<Map<String, Object>> second = new LinkedBlockingQueue<>();
        String matchId = currentMatchId();
        session.subscribe("/topic/match/" + matchId + "/score", handler(second));
        Thread.sleep(300);

        rest.postForObject(base() + "/api/matches/" + matchId + "/balls",
                ball(0, 1, 1, false), Map.class);

        assertNotNull(scoreMessages.poll(15, TimeUnit.SECONDS), "first subscriber receives it");
        assertNotNull(second.poll(15, TimeUnit.SECONDS), "second subscriber receives it too");
    }

    // ----------------------------------------------------------- helpers

    private String base() {
        return "http://localhost:" + port;
    }

    @SuppressWarnings("unchecked")
    private String currentMatchId() {
        List<Map<String, Object>> live = rest.getForObject(base() + "/api/matches/live", List.class);
        assertFalse(live.isEmpty(), "the match created in setUp must be live");
        return String.valueOf(live.get(0).get("id"));
    }

    private String createMatch() {
        Map<String, Object> created = rest.postForObject(base() + "/api/matches",
                Map.of("team1", "Team A", "team2", "Team B"), Map.class);
        return String.valueOf(created.get("id"));
    }

    private static Map<String, Object> ball(int over, int ball, int runs, boolean wicket) {
        return Map.of("inning", 1, "over", over, "ball", ball,
                "striker", "Player X", "bowler", "Bowler Y",
                "runs", runs, "wicket", wicket);
    }

    private static StompFrameHandler handler(BlockingQueue<Map<String, Object>> queue) {
        return new StompFrameHandler() {
            @Override public Type getPayloadType(StompHeaders headers) { return byte[].class; }

            @Override public void handleFrame(StompHeaders headers, Object payload) {
                try {
                    byte[] raw = (payload instanceof byte[] b)
                            ? b : String.valueOf(payload).getBytes(StandardCharsets.UTF_8);
                    @SuppressWarnings("unchecked")
                    Map<String, Object> parsed = JSON.readValue(raw, Map.class);
                    queue.offer(parsed);
                } catch (Exception e) {
                    throw new IllegalStateException("Failed to parse broadcast payload", e);
                }
            }
        };
    }
}
