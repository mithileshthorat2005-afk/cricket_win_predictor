package com.example.cricket.client;

import com.example.cricket.config.FastApiProperties;
import com.example.cricket.dto.fastapi.FastApiMcRequest;
import com.example.cricket.dto.fastapi.FastApiXgbRequest;
import com.example.cricket.exception.PredictionUnavailableException;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * FastApiClient contract tests against a real HTTP server (MockWebServer).
 * Verifies: success mapping, 4xx detail propagation, 5xx, timeout and
 * connection-refused handling - the client must never fabricate a result.
 */
class FastApiClientTest {

    private MockWebServer server;
    private FastApiClient client;

    @BeforeEach
    void setUp() throws IOException {
        server = new MockWebServer();
        server.start();
        // Generous timeouts: MockWebServer on a loaded Windows host can be
        // slow; the dedicated timeout test builds its own tight client.
        client = new FastApiClient(new FastApiProperties(
                server.url("/").toString(), 5000, 10000, 20000));
    }

    @AfterEach
    void tearDown() throws IOException {
        server.shutdown();
    }

    private static FastApiXgbRequest xgbRequest() {
        return new FastApiXgbRequest(1, 2, "Mumbai Indians", "Chennai Super Kings",
                12.3, 110, 3, 170);
    }

    @Test
    void predictXgb_mapsSuccessResponse() throws Exception {
        server.enqueue(new MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody("""
                        {"win_probability":0.623,"batting_team":"Mumbai Indians",
                         "bowling_team":"Chennai Super Kings","inning":2,
                         "confidence":"Medium","key_factors":["High required run rate"]}
                        """));

        var response = client.predictXgb(xgbRequest());

        assertEquals(0.623, response.winProbability(), 1e-9);
        assertEquals("Medium", response.confidence());
        assertEquals(1, response.keyFactors().size());

        // Request path + body
        assertEquals("/predict", server.takeRequest().getPath());
    }

    @Test
    void predictXgb_4xx_carriesFastApiDetail() {
        server.enqueue(new MockResponse()
                .setResponseCode(400)
                .setHeader("Content-Type", "application/json")
                .setBody("{\"detail\":\"Unknown batting team: Fake Team\"}"));

        PredictionUnavailableException ex = assertThrows(
                PredictionUnavailableException.class, () -> client.predictXgb(xgbRequest()));
        assertTrue(ex.getMessage().contains("Unknown batting team: Fake Team"));
        assertTrue(ex.getMessage().contains("400"));
    }

    @Test
    void predictXgb_5xx_becomesUnavailable() {
        server.enqueue(new MockResponse().setResponseCode(500).setBody("boom"));

        assertThrows(PredictionUnavailableException.class,
                () -> client.predictXgb(xgbRequest()));
    }

    @Test
    void predictXgb_connectionRefused_becomesUnavailable() throws IOException {
        server.shutdown(); // nothing listening anymore

        PredictionUnavailableException ex = assertThrows(
                PredictionUnavailableException.class, () -> client.predictXgb(xgbRequest()));
        assertNotNull(ex.getCause());
    }

    @Test
    void predictXgb_timeout_becomesUnavailable() throws IOException {
        // Dedicated client with a tight 500ms response timeout
        FastApiClient impatient = new FastApiClient(new FastApiProperties(
                server.url("/").toString(), 500, 500, 20000));
        server.enqueue(new MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody("{\"win_probability\":0.5}")
                .setBodyDelay(3, TimeUnit.SECONDS)); // > 500ms response timeout

        PredictionUnavailableException ex = assertThrows(
                PredictionUnavailableException.class, () -> impatient.predictXgb(xgbRequest()));
        assertTrue(ex.getMessage().contains("timed out"));
    }

    @Test
    void predictMonteCarlo_mapsScoreAndProbability() throws Exception {
        server.enqueue(new MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody("""
                        {"inning":2,"win_probability":0.7142,"predicted_score":null,
                         "confidence_interval":null,"simulations":300,
                         "note":"Probability that the batting team wins the chase."}
                        """));

        var request = new FastApiMcRequest(1, 2, 15, 3, 120, 4, 162, 300, null, null);
        var response = client.predictMonteCarlo(request);

        assertEquals(0.7142, response.winProbability(), 1e-9);
        assertNull(response.predictedScore());
        assertEquals(300, response.simulations());
        assertEquals("/predict/montecarlo", server.takeRequest().getPath());
    }

    @Test
    void predictMonteCarlo_unknownPlayer_400_carriesDetail() {
        server.enqueue(new MockResponse()
                .setResponseCode(400)
                .setHeader("Content-Type", "application/json")
                .setBody("{\"detail\":\"Unknown player 'Nobody Real' in striker\"}"));

        var striker = new FastApiMcRequest.Batsman("Nobody Real", null, 0, 0);
        var request = new FastApiMcRequest(1, 2, 10, 1, 80, 2, 180, 50, striker, null);

        PredictionUnavailableException ex = assertThrows(
                PredictionUnavailableException.class, () -> client.predictMonteCarlo(request));
        assertTrue(ex.getMessage().contains("Nobody Real"));
    }

    @Test
    void isHealthy_reflectsServerState() throws IOException {
        server.enqueue(new MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody("{\"status\":\"healthy\"}"));
        assertTrue(client.isHealthy());

        server.shutdown();
        assertFalse(client.isHealthy());
    }
}
