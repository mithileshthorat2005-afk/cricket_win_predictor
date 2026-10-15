package com.example.cricket.client;

import com.example.cricket.config.FastApiProperties;
import com.example.cricket.dto.fastapi.*;
import com.example.cricket.exception.PredictionUnavailableException;
import io.netty.channel.ChannelOption;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.concurrent.TimeoutException;

/**
 * HTTP client for the Python FastAPI ML microservice.
 *
 * Error policy:
 *  - 4xx from FastAPI (invalid state, unknown player, ...) -> PredictionUnavailable
 *    carrying FastAPI's 'detail' message; we never invent a result.
 *  - Connection refused / timeouts / 5xx -> PredictionUnavailable.
 * The response timeout is generous because the montecarlo path runs
 * simulations and can take tens of seconds under load.
 */
@Component
public class FastApiClient {

    private static final Logger log = LoggerFactory.getLogger(FastApiClient.class);

    private final WebClient webClient;
    private final Duration responseTimeout;
    private final Duration healthTimeout;

    public FastApiClient(FastApiProperties props) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, props.connectTimeoutMs())
                .responseTimeout(Duration.ofMillis(props.responseTimeoutMs()));
        this.webClient = WebClient.builder()
                .baseUrl(props.baseUrl())
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
        this.responseTimeout = Duration.ofMillis(props.responseTimeoutMs());
        this.healthTimeout = Duration.ofMillis(props.healthTimeoutMs());
        log.info("FastAPI client initialised. baseUrl={}, connectTimeoutMs={}, responseTimeoutMs={}, healthTimeoutMs={}",
                props.baseUrl(), props.connectTimeoutMs(), props.responseTimeoutMs(), props.healthTimeoutMs());
    }

    /** POST /predict - XGBoost classifier win probability. */
    public FastApiXgbResponse predictXgb(FastApiXgbRequest request) {
        return webClient.post()
                .uri("/predict")
                .bodyValue(request)
                .retrieve()
                .bodyToMono(FastApiXgbResponse.class)
                .timeout(responseTimeout)
                .onErrorMap(WebClientResponseException.class, e -> translate("predict", e))
                .onErrorMap(TimeoutException.class, e -> new PredictionUnavailableException(
                        "FastAPI /predict timed out after " + responseTimeout.toMillis() + " ms", e))
                .onErrorMap(e -> !(e instanceof PredictionUnavailableException),
                        e -> new PredictionUnavailableException("FastAPI /predict failed: " + e.getMessage(), e))
                .block(responseTimeout.plusSeconds(5));
    }

    /** POST /predict/montecarlo - Monte Carlo simulation over the ball-outcome model. */
    public FastApiMcResponse predictMonteCarlo(FastApiMcRequest request) {
        return webClient.post()
                .uri("/predict/montecarlo")
                .bodyValue(request)
                .retrieve()
                .bodyToMono(FastApiMcResponse.class)
                .timeout(responseTimeout)
                .onErrorMap(WebClientResponseException.class, e -> translate("montecarlo", e))
                .onErrorMap(TimeoutException.class, e -> new PredictionUnavailableException(
                        "FastAPI /predict/montecarlo timed out after " + responseTimeout.toMillis() + " ms", e))
                .onErrorMap(e -> !(e instanceof PredictionUnavailableException),
                        e -> new PredictionUnavailableException("FastAPI /predict/montecarlo failed: " + e.getMessage(), e))
                .block(responseTimeout.plusSeconds(5));
    }

    /** GET /health - surfaced by the orchestrator's readiness info. */
    public boolean isHealthy() {
        try {
            webClient.get().uri("/health").retrieve()
                    .bodyToMono(String.class)
                    .timeout(healthTimeout)
                    .block();
            return true;
        } catch (Exception e) {
            log.warn("FastAPI health check failed: {}", e.getMessage());
            return false;
        }
    }

    private PredictionUnavailableException translate(String op, WebClientResponseException e) {
        String detail = null;
        try {
            FastApiError err = e.getResponseBodyAs(FastApiError.class);
            detail = err != null ? err.detail() : null;
        } catch (Exception ignored) {
            // body may not be a FastAPI error envelope
        }
        String message = detail != null
                ? "FastAPI /" + op + " rejected the request (HTTP " + e.getStatusCode().value() + "): " + detail
                : "FastAPI /" + op + " returned HTTP " + e.getStatusCode().value();
        return new PredictionUnavailableException(message, e);
    }
}
