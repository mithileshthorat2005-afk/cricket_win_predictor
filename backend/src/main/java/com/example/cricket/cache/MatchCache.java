package com.example.cricket.cache;

import com.example.cricket.config.CacheProperties;
import com.example.cricket.dto.MatchStateResponse;
import com.example.cricket.model.Prediction;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Optional;

/**
 * Redis cache for frequently accessed match state and prediction results.
 *
 * Cache keys
 * ----------
 *   match:state:{matchId}
 *       Latest MatchStateResponse JSON. Updated on every accepted ball event,
 *       so it always equals the committed database state.
 *
 *   match:pred:{matchId}:v{stateVersion}:{model}:{simulations}:{battingTeam}
 *   [:{strikerName|q}:{quality}:{nonStrikerName|q}:{quality}]
 *       A prediction result. The key includes EVERY prediction-relevant
 *       dimension - match id, match-state version (bumped per accepted ball),
 *       model type, simulation count and batsman context - so two different
 *       match states can NEVER collide on the same cached prediction.
 *       stateVersion alone guarantees per-ball uniqueness; the remaining
 *       dimensions separate different request types for the same state.
 *
 * Failure policy: any Redis error is logged once and treated as a cache
 * miss / skipped write. The cache is a pure optimisation - correctness never
 * depends on it, and a prediction failure is NEVER cached.
 */
@Component
public class MatchCache {

    private static final Logger log = LoggerFactory.getLogger(MatchCache.class);

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;
    private final CacheProperties props;
    private volatile boolean redisBrokenLogged = false;

    public MatchCache(StringRedisTemplate redis, ObjectMapper objectMapper, CacheProperties props) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.props = props;
    }

    // ------------------------------------------------------------ state

    public Optional<MatchStateResponse> getState(Long matchId) {
        if (!props.enabled()) return Optional.empty();
        try {
            String json = redis.opsForValue().get(stateKey(matchId));
            if (json == null) return Optional.empty();
            return Optional.of(objectMapper.readValue(json, MatchStateResponse.class));
        } catch (Exception e) {
            logRedisDegraded("state read", e);
            return Optional.empty();
        }
    }

    public void putState(MatchStateResponse state) {
        if (!props.enabled()) return;
        try {
            redis.opsForValue().set(stateKey(state.matchId()),
                    objectMapper.writeValueAsString(state),
                    Duration.ofSeconds(props.stateTtlSeconds()));
        } catch (Exception e) {
            logRedisDegraded("state write", e);
        }
    }

    /** Invalidate on ingestion so a stale state can never be served. */
    public void evictState(Long matchId) {
        if (!props.enabled()) return;
        try {
            redis.delete(stateKey(matchId));
        } catch (Exception e) {
            logRedisDegraded("state evict", e);
        }
    }

    // -------------------------------------------------------- predictions

    /**
     * Build a prediction cache key from every prediction-relevant dimension.
     * Two requests with different match state (stateVersion), model,
     * simulation count or batsman context get different keys.
     */
    public String predictionKey(Long matchId, long stateVersion, String model,
                                int simulations, String battingTeam,
                                String strikerPart, String nonStrikerPart) {
        StringBuilder key = new StringBuilder()
                .append("match:pred:").append(matchId)
                .append(":v").append(stateVersion)
                .append(':').append(model)
                .append(':').append(simulations)
                .append(':').append(battingTeam == null ? "-" : battingTeam.hashCode());
        if (strikerPart != null) key.append(":s").append(strikerPart.hashCode());
        if (nonStrikerPart != null) key.append(":n").append(nonStrikerPart.hashCode());
        return key.toString();
    }

    public Optional<Prediction> getPrediction(String key) {
        if (!props.enabled()) return Optional.empty();
        try {
            String json = redis.opsForValue().get(key);
            if (json == null) return Optional.empty();
            return Optional.of(objectMapper.readValue(json, Prediction.class));
        } catch (Exception e) {
            logRedisDegraded("prediction read", e);
            return Optional.empty();
        }
    }

    public void putPrediction(String key, Prediction prediction) {
        if (!props.enabled()) return;
        try {
            redis.opsForValue().set(key, objectMapper.writeValueAsString(prediction),
                    Duration.ofSeconds(props.predictionTtlSeconds()));
        } catch (Exception e) {
            logRedisDegraded("prediction write", e);
        }
    }

    private static String stateKey(Long matchId) {
        return "match:state:" + matchId;
    }

    private void logRedisDegraded(String action, Exception e) {
        if (!redisBrokenLogged) {
            redisBrokenLogged = true;
            log.warn("Redis unavailable ({}: {}). Continuing WITHOUT cache - " +
                    "this warning is logged once per JVM run.", action, e.getMessage());
        }
    }
}
