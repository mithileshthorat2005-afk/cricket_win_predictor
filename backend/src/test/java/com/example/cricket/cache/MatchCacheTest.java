package com.example.cricket.cache;

import com.example.cricket.config.CacheProperties;
import com.example.cricket.dto.MatchStateResponse;
import com.example.cricket.model.Prediction;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * MatchCache unit tests with a mocked Redis template.
 * Covers: hit, miss, expiry-aware writes, Redis outage fallback (never throws),
 * disabled cache (no Redis traffic), and key sensitivity to state changes.
 */
class MatchCacheTest {

    private StringRedisTemplate redis;
    @SuppressWarnings("unchecked")
    private ValueOperations<String, String> valueOps = mock(ValueOperations.class);
    private MatchCache cache;
    // Spring's auto-configured ObjectMapper (production path) includes the
    // JSR310 module for Instant; a raw ObjectMapper does not - register it.
    private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules();

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenReturn(valueOps);
        cache = new MatchCache(redis, mapper,
                new CacheProperties(true, 300, 600));
    }

    private static MatchStateResponse state(long version) {
        return new MatchStateResponse(1L, 2, "Team B", "Team A",
                12.3, 110, 3, 75, 45, 170, version);
    }

    // ------------------------------------------------------------- state

    @Test
    void stateHit_returnsDeserializedState() throws Exception {
        when(valueOps.get("match:state:1"))
                .thenReturn(mapper.writeValueAsString(state(7)));

        var result = cache.getState(1L);

        assertTrue(result.isPresent());
        assertEquals(110, result.get().runs());
        assertEquals(7, result.get().stateVersion());
    }

    @Test
    void stateMiss_returnsEmpty() {
        when(valueOps.get("match:state:1")).thenReturn(null);
        assertEquals(Optional.empty(), cache.getState(1L));
    }

    @Test
    void statePut_usesTtl() throws Exception {
        cache.putState(state(9));
        verify(valueOps).set(eq("match:state:1"),
                eq(mapper.writeValueAsString(state(9))),
                eq(Duration.ofSeconds(300)));
    }

    @Test
    void evictState_deletesKey() {
        cache.evictState(42L);
        verify(redis).delete("match:state:42");
    }

    // -------------------------------------------------------- predictions

    @Test
    void predictionKey_isSensitiveToEveryRelevantDimension() {
        String base = cache.predictionKey(1L, 5, "montecarlo", 300, "Team B", null, null);
        assertEquals(base, cache.predictionKey(1L, 5, "montecarlo", 300, "Team B", null, null),
                "identical state -> identical key");

        assertNotEquals(base, cache.predictionKey(2L, 5, "montecarlo", 300, "Team B", null, null),
                "different match");
        assertNotEquals(base, cache.predictionKey(1L, 6, "montecarlo", 300, "Team B", null, null),
                "different stateVersion (a new ball was bowled)");
        assertNotEquals(base, cache.predictionKey(1L, 5, "xgboost", 300, "Team B", null, null),
                "different model");
        assertNotEquals(base, cache.predictionKey(1L, 5, "montecarlo", 500, "Team B", null, null),
                "different simulation count");
        assertNotEquals(base, cache.predictionKey(1L, 5, "montecarlo", 300, "Team C", null, null),
                "different batting team");
        assertNotEquals(base, cache.predictionKey(1L, 5, "montecarlo", 300, "Team B", "V Kohli|", null),
                "different striker");
    }

    @Test
    void predictionHit_returnsDeserializedPrediction() throws Exception {
        Prediction p = new Prediction(1L, 2, 5, "montecarlo", 0.71, 160.0, 1200);
        when(valueOps.get("k")).thenReturn(mapper.writeValueAsString(p));

        var result = cache.getPrediction("k");

        assertTrue(result.isPresent());
        assertEquals(0.71, result.get().getWinProbability(), 1e-9);
        assertEquals(5, result.get().getStateVersion());
    }

    @Test
    void predictionMiss_returnsEmpty() {
        when(valueOps.get("k")).thenReturn(null);
        assertEquals(Optional.empty(), cache.getPrediction("k"));
    }

    @Test
    void predictionPut_usesTtl() throws Exception {
        Prediction p = new Prediction(1L, 2, 5, "montecarlo", 0.71, null, 900);
        cache.putPrediction("k", p);
        verify(valueOps).set(eq("k"), eq(mapper.writeValueAsString(p)),
                eq(Duration.ofSeconds(600)));
    }

    // ------------------------------------------------------------- safety

    @Test
    void redisOutage_onRead_treatedAsMiss_neverThrows() {
        when(valueOps.get(anyString())).thenThrow(new RuntimeException("connection refused"));
        assertEquals(Optional.empty(), cache.getState(1L));
        assertEquals(Optional.empty(), cache.getPrediction("k"));
    }

    @Test
    void redisOutage_onWrite_swallowed() {
        when(valueOps.get(anyString())).thenReturn(null);
        doThrow(new RuntimeException("connection refused"))
                .when(valueOps).set(anyString(), anyString(), any(Duration.class));
        assertDoesNotThrow(() -> cache.putState(state(1)));
        assertDoesNotThrow(() -> cache.putPrediction("k",
                new Prediction(1L, 2, 1, "xgboost", 0.5, null, 10)));
    }

    @Test
    void disabledCache_neverTouchesRedis() {
        MatchCache off = new MatchCache(redis, mapper, new CacheProperties(false, 300, 600));
        off.putState(state(1));
        off.evictState(1L);
        assertEquals(Optional.empty(), off.getState(1L));
        assertEquals(Optional.empty(), off.getPrediction("k"));
        verifyNoInteractions(valueOps);
    }
}
