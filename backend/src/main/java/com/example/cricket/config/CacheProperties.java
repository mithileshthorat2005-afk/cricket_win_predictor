package com.example.cricket.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Redis cache settings. The cache is a pure optimisation: when Redis is
 * unreachable the application keeps working (cache reads/writes degrade to
 * misses - see MatchCache).
 */
@ConfigurationProperties(prefix = "cricket.cache")
public record CacheProperties(boolean enabled,
                              int stateTtlSeconds,
                              int predictionTtlSeconds) {
}
