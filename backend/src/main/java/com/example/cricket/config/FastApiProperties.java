package com.example.cricket.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Connection settings for the FastAPI ML microservice.
 * Bound from the 'cricket.fastapi.*' prefix in application.properties.
 */
@ConfigurationProperties(prefix = "cricket.fastapi")
public record FastApiProperties(String baseUrl,
                                int connectTimeoutMs,
                                int responseTimeoutMs,
                                int healthTimeoutMs) {
}
