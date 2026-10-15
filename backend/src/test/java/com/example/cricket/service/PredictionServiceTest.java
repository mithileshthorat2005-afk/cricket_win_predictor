package com.example.cricket.service;

import com.example.cricket.client.FastApiClient;
import com.example.cricket.dto.BallEventRequest;
import com.example.cricket.dto.CreateMatchRequest;
import com.example.cricket.dto.PredictionResultResponse;
import com.example.cricket.dto.fastapi.FastApiMcRequest;
import com.example.cricket.dto.fastapi.FastApiMcResponse;
import com.example.cricket.dto.fastapi.FastApiXgbRequest;
import com.example.cricket.dto.fastapi.FastApiXgbResponse;
import com.example.cricket.exception.InvalidMatchStateException;
import com.example.cricket.exception.PredictionUnavailableException;
import com.example.cricket.repository.PredictionRepository;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * PredictionService tests with FastApiClient mocked (no real ML service).
 * Verifies state-version snapshotting, model routing, error propagation
 * (never fabricating a probability) and persistence.
 */
@SpringBootTest
@ActiveProfiles("test")
class PredictionServiceTest {

    @Autowired private MatchService matchService;
    @Autowired private PredictionService predictionService;
    @Autowired private PredictionRepository predictionRepository;

    @MockitoBean private FastApiClient fastApiClient;

    private Long matchWithTwoBalls() {
        Long id = matchService.createMatch(new CreateMatchRequest("Team A", "Team B")).id();
        matchService.ingestBall(id, new BallEventRequest(null, 1, 0, 1, "Player X", null, "Bowler Y", 4, false));
        matchService.ingestBall(id, new BallEventRequest(null, 1, 0, 2, "Player X", null, "Bowler Y", 1, false));
        return id;
    }

    @Test
    void xgboostPrediction_snapshotsStateVersionAndPersists() {
        Long id = matchWithTwoBalls();
        long predictionsBefore = predictionRepository.count();
        when(fastApiClient.predictXgb(any())).thenReturn(
                new FastApiXgbResponse(0.623, "Team A", "Team B", 1, "Medium", List.of("factor")));

        PredictionResultResponse result = predictionService.predict(id, "xgboost", null, null, null);

        assertEquals(2, result.stateVersion(), "version snapshot must match pre-call state");
        assertEquals(0.623, result.winProbability(), 1e-9);
        assertEquals("xgboost", result.modelType());
        assertFalse(result.stale());

        // Correct request shape sent to FastAPI
        ArgumentCaptor<FastApiXgbRequest> captor = ArgumentCaptor.forClass(FastApiXgbRequest.class);
        verify(fastApiClient).predictXgb(captor.capture());
        FastApiXgbRequest sent = captor.getValue();
        assertEquals(0.2, sent.oversCompleted(), 1e-9); // 2 balls bowled = 0.2 overs
        assertEquals(5, sent.runsScored());
        assertNull(sent.target(), "first innings has no target");

        // H2 DB shared across tests: assert exactly one NEW prediction row
        assertEquals(predictionsBefore + 1, predictionRepository.count());
    }

    @Test
    void montecarloPrediction_mapsToRequestAndResponse() {
        Long id = matchWithTwoBalls();
        when(fastApiClient.predictMonteCarlo(any())).thenReturn(
                new FastApiMcResponse(1, null, 158.4, List.of(130.0, 187.0), 300, "score prediction"));

        PredictionResultResponse result = predictionService.predict(id, "montecarlo", 300, null, null);

        assertNull(result.winProbability(), "first-innings montecarlo must not fabricate a probability");
        assertEquals(158.4, result.predictedScore(), 1e-9);

        ArgumentCaptor<FastApiMcRequest> captor = ArgumentCaptor.forClass(FastApiMcRequest.class);
        verify(fastApiClient).predictMonteCarlo(captor.capture());
        FastApiMcRequest sent = captor.getValue();
        assertEquals(0, sent.over());
        assertEquals(2, sent.ball()); // 2 balls bowled
        assertEquals(300, sent.nSimulations());
    }

    @Test
    void montecarlo_ballOnOverBoundary_mapsToBallSixOfPreviousOver() {
        Long id = matchService.createMatch(new CreateMatchRequest("Team A", "Team B")).id();
        // 6 legal balls -> exactly 1.0 overs: must be sent as over=0, ball=6
        for (int b = 1; b <= 6; b++) {
            matchService.ingestBall(id, new BallEventRequest(null, 1, 0, b, "Player X", null, "Bowler Y", 1, false));
        }
        when(fastApiClient.predictMonteCarlo(any())).thenReturn(
                new FastApiMcResponse(1, null, 150.0, List.of(120.0, 180.0), 300, "note"));

        predictionService.predict(id, "montecarlo", null, null, null);

        ArgumentCaptor<FastApiMcRequest> captor = ArgumentCaptor.forClass(FastApiMcRequest.class);
        verify(fastApiClient).predictMonteCarlo(captor.capture());
        assertEquals(0, captor.getValue().over());
        assertEquals(6, captor.getValue().ball());
    }

    @Test
    void fastApiFailure_propagates_andStoresNothing() {
        Long id = matchWithTwoBalls();
        long before = predictionRepository.count();
        when(fastApiClient.predictXgb(any())).thenThrow(
                new PredictionUnavailableException("FastAPI /predict rejected: unknown team"));

        assertThrows(PredictionUnavailableException.class,
                () -> predictionService.predict(id, "xgboost", null, null, null));
        // H2 is shared across tests in this class: assert no NEW row was stored
        assertEquals(before, predictionRepository.count(),
                "failed predictions must not be cached/stored");
    }

    @Test
    void unknownModel_rejected() {
        Long id = matchWithTwoBalls();
        assertThrows(InvalidMatchStateException.class,
                () -> predictionService.predict(id, "neuralnet", null, null, null));
    }

    @Test
    void predictionAfterNewBall_isFlaggedStale() {
        Long id = matchWithTwoBalls();
        when(fastApiClient.predictXgb(any())).thenReturn(
                new FastApiXgbResponse(0.5, "Team A", "Team B", 1, "Low", List.of()));

        PredictionResultResponse p = predictionService.predict(id, "xgboost", null, null, null);
        assertFalse(p.stale());

        // A new ball arrives -> version advances -> old prediction is stale
        matchService.ingestBall(id, new BallEventRequest(null, 1, 0, 3, "Player X", null, "Bowler Y", 1, false));
        var history = matchService.getPredictions(id);
        assertEquals(1, history.size());
        assertTrue(history.get(0).stale(), "prediction from previous version must be flagged stale");
    }
}
