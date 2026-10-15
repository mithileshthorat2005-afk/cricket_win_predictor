package com.example.cricket.service;

import com.example.cricket.cache.MatchCache;
import com.example.cricket.client.FastApiClient;
import com.example.cricket.dto.PredictionResultResponse;
import com.example.cricket.dto.fastapi.*;
import com.example.cricket.exception.InvalidMatchStateException;
import com.example.cricket.exception.MatchNotFoundException;
import com.example.cricket.model.Innings;
import com.example.cricket.model.Match;
import com.example.cricket.model.Prediction;
import com.example.cricket.repository.InningsRepository;
import com.example.cricket.repository.MatchRepository;
import com.example.cricket.repository.PredictionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

/**
 * Orchestrates predictions: current match state -> FastAPI ML service ->
 * persisted Prediction carrying the match-state version it was computed from.
 *
 * The FastAPI call happens OUTSIDE any database transaction so a slow
 * montecarlo run never holds database locks.
 */
@Service
public class PredictionService {

    public static final String MODEL_XGBOOST = "xgboost";
    public static final String MODEL_MONTECARLO = "montecarlo";

    private static final Logger log = LoggerFactory.getLogger(PredictionService.class);

    private final MatchRepository matchRepository;
    private final InningsRepository inningsRepository;
    private final PredictionRepository predictionRepository;
    private final FastApiClient fastApiClient;
    private final MatchCache matchCache;
    private final int defaultSimulations;

    /** Optional batsman context for the montecarlo path (names must exist in
     *  the 516-player database unless an explicit quality is supplied). */
    public record BatsmanContext(String name, Double quality) {
    }

    public PredictionService(MatchRepository matchRepository,
                             InningsRepository inningsRepository,
                             PredictionRepository predictionRepository,
                             FastApiClient fastApiClient,
                             MatchCache matchCache,
                             @Value("${cricket.prediction.mc-simulations:300}") int defaultSimulations) {
        this.matchRepository = matchRepository;
        this.inningsRepository = inningsRepository;
        this.predictionRepository = predictionRepository;
        this.fastApiClient = fastApiClient;
        this.matchCache = matchCache;
        this.defaultSimulations = defaultSimulations;
    }

    @Transactional
    public PredictionResultResponse predict(Long matchId,
                                            String modelType,
                                            Integer nSimulations,
                                            BatsmanContext striker,
                                            BatsmanContext nonStriker) {
        Match match = matchRepository.findById(matchId)
                .orElseThrow(() -> new MatchNotFoundException(matchId));
        Innings innings = inningsRepository
                .findByMatchIdAndInningNumber(matchId, match.getCurrentInnings())
                .orElseThrow(() -> new InvalidMatchStateException(
                        "No innings state yet for match " + matchId));
        if (innings.isCompleted()) {
            throw new InvalidMatchStateException(
                    "Innings " + innings.getInningNumber() + " of match " + matchId + " is complete");
        }

        String model = (modelType == null || modelType.isBlank())
                ? MODEL_XGBOOST : modelType.toLowerCase();

        int simulations = nSimulations != null ? nSimulations : defaultSimulations;

        // Snapshot the version BEFORE the (possibly slow) ML call. This is the
        // version stored with the prediction and used for the stale check.
        long versionAtRequest = match.getStateVersion();

        // ---- Redis prediction cache ----------------------------------------
        // The key contains stateVersion (bumped per accepted ball), model,
        // simulation count and batsman context: a cached result can never be
        // served for a different match state.
        String cacheKey = matchCache.predictionKey(matchId, versionAtRequest, model,
                simulations, innings.getBattingTeam(),
                strikerKeyPart(striker), strikerKeyPart(nonStriker));
        var cached = matchCache.getPrediction(cacheKey);
        if (cached.isPresent()) {
            log.info("Prediction cache HIT: match={} model={} version={}",
                    matchId, model, versionAtRequest);
            return MatchService.toPredictionResponse(cached.get(), versionAtRequest);
        }

        Prediction prediction = switch (model) {
            case MODEL_XGBOOST -> callXgb(match, innings, versionAtRequest);
            case MODEL_MONTECARLO -> callMonteCarlo(match, innings, versionAtRequest,
                    simulations, striker, nonStriker);
            default -> throw new InvalidMatchStateException(
                    "Unknown model type '" + model + "' (use 'xgboost' or 'montecarlo')");
        };

        Prediction saved = predictionRepository.save(prediction);
        // Only successful predictions are cached (failures never reach here).
        matchCache.putPrediction(cacheKey, saved);
        log.info("Prediction stored: match={} model={} version={} winProb={} score={} ({} ms)",
                matchId, model, saved.getStateVersion(), saved.getWinProbability(),
                saved.getPredictedScore(), saved.getLatencyMs());

        long liveVersion = matchRepository.findById(matchId).map(Match::getStateVersion).orElse(versionAtRequest);
        return MatchService.toPredictionResponse(saved, liveVersion);
    }

    private static String strikerKeyPart(BatsmanContext ctx) {
        if (ctx == null) return null;
        return (ctx.name() != null ? ctx.name() : "") + "|" + (ctx.quality() != null ? ctx.quality() : "");
    }

    // ------------------------------------------------------------- internal

    private Prediction callXgb(Match match, Innings innings, long versionAtRequest) {
        var request = new FastApiXgbRequest(
                Math.toIntExact(match.getId()),
                innings.getInningNumber(),
                innings.getBattingTeam(),
                innings.getBowlingTeam(),
                MatchService.toOvers(innings.getBallsBowled()),
                innings.getRuns(),
                innings.getWickets(),
                innings.getTarget());

        long start = System.currentTimeMillis();
        FastApiXgbResponse response = fastApiClient.predictXgb(request);
        long latency = System.currentTimeMillis() - start;

        return new Prediction(match.getId(), innings.getInningNumber(), versionAtRequest,
                MODEL_XGBOOST, response.winProbability(), null, latency);
    }

    private Prediction callMonteCarlo(Match match, Innings innings, long versionAtRequest,
                                      int nSimulations,
                                      BatsmanContext striker, BatsmanContext nonStriker) {
        // FastAPI montecarlo wants over/ball as (over 0-20, ball 1-6);
        // an exact over boundary maps to ball 6 of the previous over.
        int balls = innings.getBallsBowled();
        int over = balls / 6;
        int ball = balls % 6;
        if (ball == 0 && balls > 0) {
            over -= 1;
            ball = 6;
        }

        var request = new FastApiMcRequest(
                Math.toIntExact(match.getId()),
                innings.getInningNumber(),
                over, ball,
                innings.getRuns(),
                innings.getWickets(),
                innings.getTarget(),
                nSimulations,
                toMcBatsman(striker),
                toMcBatsman(nonStriker));

        long start = System.currentTimeMillis();
        FastApiMcResponse response = fastApiClient.predictMonteCarlo(request);
        long latency = System.currentTimeMillis() - start;

        // First-innings montecarlo returns a score, NOT a win probability:
        // winProbability stays null (never a fabricated 0.0).
        return new Prediction(match.getId(), innings.getInningNumber(), versionAtRequest,
                MODEL_MONTECARLO, response.winProbability(), response.predictedScore(), latency);
    }

    private static FastApiMcRequest.Batsman toMcBatsman(BatsmanContext ctx) {
        if (ctx == null || (ctx.name() == null && ctx.quality() == null)) {
            return null;
        }
        return new FastApiMcRequest.Batsman(ctx.name(), ctx.quality(), 0, 0);
    }
}
