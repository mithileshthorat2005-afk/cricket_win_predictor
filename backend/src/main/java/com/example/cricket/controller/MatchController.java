package com.example.cricket.controller;

import com.example.cricket.dto.*;
import com.example.cricket.model.Delivery;
import com.example.cricket.service.MatchService;
import com.example.cricket.service.PredictionService;
import com.example.cricket.service.WebSocketPublisher;
import jakarta.validation.Valid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Application-facing REST API for match management and live prediction.
 *
 * Ingestion flow per accepted ball (POST /{id}/balls):
 *   1. validate + persist the event (MatchService, transactional, idempotent)
 *   2. publish the new score + ball over WebSocket (only after commit)
 *   3. optionally request a prediction from FastAPI (cricket.prediction.auto-on-ball)
 *   4. persist the prediction and publish it (stale-guarded by stateVersion)
 * A failed prediction NEVER fails the ingestion and NEVER fabricates a
 * probability - the response carries the error message instead.
 */
@RestController
@RequestMapping("/api/matches")
public class MatchController {

    private static final Logger log = LoggerFactory.getLogger(MatchController.class);

    private final MatchService matchService;
    private final PredictionService predictionService;
    private final WebSocketPublisher webSocketPublisher;
    private final boolean autoPredictOnBall;

    public MatchController(MatchService matchService,
                           PredictionService predictionService,
                           WebSocketPublisher webSocketPublisher,
                           @Value("${cricket.prediction.auto-on-ball:true}") boolean autoPredictOnBall) {
        this.matchService = matchService;
        this.predictionService = predictionService;
        this.webSocketPublisher = webSocketPublisher;
        this.autoPredictOnBall = autoPredictOnBall;
    }

    @PostMapping
    public ResponseEntity<MatchResponse> createMatch(@Valid @RequestBody CreateMatchRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(matchService.createMatch(request));
    }

    @GetMapping("/live")
    public List<MatchResponse> liveMatches() {
        return matchService.listLive();
    }

    @GetMapping("/{id}")
    public MatchResponse getMatch(@PathVariable Long id) {
        return matchService.getMatch(id);
    }

    @GetMapping("/{id}/state")
    public MatchStateResponse getState(@PathVariable Long id) {
        return matchService.getState(id);
    }

    @PostMapping("/{id}/balls")
    public IngestBallResponse ingestBall(@PathVariable Long id,
                                         @Valid @RequestBody BallEventRequest event) {
        MatchService.IngestResult result = matchService.ingestBall(id, event);

        // Duplicate: nothing changed, nothing re-published, no double count.
        if (result.duplicate()) {
            MatchStateResponse state = matchService.getState(id);
            return new IngestBallResponse(true, id, state, null, null);
        }

        // Publish AFTER the transaction committed - failed ingestion is never broadcast.
        MatchStateResponse state = matchService.getState(id);
        webSocketPublisher.publishScore(state);
        webSocketPublisher.publishBall(id, state.inning(),
                buildPublishedDelivery(id, event, state.stateVersion()));

        PredictionResultResponse prediction = null;
        String predictionError = null;
        if (autoPredictOnBall) {
            try {
                prediction = predictionService.predict(id, null, null, null, null);
                webSocketPublisher.publishProbability(new com.example.cricket.model.Prediction(
                        id, prediction.inning(), prediction.stateVersion(),
                        prediction.modelType(),
                        prediction.winProbability(),
                        prediction.predictedScore(), prediction.latencyMs()));
            } catch (Exception e) {
                // Ingestion succeeded; surface the ML failure without inventing numbers.
                log.warn("Auto-prediction failed for match {} (ball was accepted): {}", id, e.getMessage());
                predictionError = e.getMessage();
            }
        }

        return new IngestBallResponse(false, id, state, prediction, predictionError);
    }

    @PostMapping("/{id}/predict")
    public PredictionResultResponse predict(@PathVariable Long id,
                                            @RequestBody(required = false) PredictOptions options) {
        PredictOptions opts = options != null ? options : PredictOptions.defaults();
        PredictionResultResponse result = predictionService.predict(
                id, opts.model(), opts.nSimulations(),
                new PredictionService.BatsmanContext(opts.strikerName(), opts.strikerQuality()),
                new PredictionService.BatsmanContext(opts.nonStrikerName(), opts.nonStrikerQuality()));
        webSocketPublisher.publishProbability(new com.example.cricket.model.Prediction(
                id, result.inning(), result.stateVersion(), result.modelType(),
                result.winProbability(),
                result.predictedScore(), result.latencyMs()));
        return result;
    }

    @GetMapping("/{id}/predictions")
    public List<PredictionResultResponse> predictions(@PathVariable Long id) {
        return matchService.getPredictions(id);
    }

    /**
     * Build the delivery snapshot used for the /ball WebSocket broadcast from
     * the accepted event (stateVersion = version AFTER the ball).
     */
    private static Delivery buildPublishedDelivery(Long matchId, BallEventRequest e, long version) {
        return new Delivery(matchId, null, e.eventId() != null ? e.eventId() : "",
                e.over(), e.ball(), e.striker(), e.nonStriker(), e.bowler(),
                e.runs(), e.wicket(), version);
    }

    /** Optional body for POST /{id}/predict. */
    public record PredictOptions(String model,
                                 Integer nSimulations,
                                 String strikerName,
                                 Double strikerQuality,
                                 String nonStrikerName,
                                 Double nonStrikerQuality) {
        static PredictOptions defaults() {
            return new PredictOptions(null, null, null, null, null, null);
        }
    }
}
