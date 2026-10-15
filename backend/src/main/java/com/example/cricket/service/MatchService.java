package com.example.cricket.service;

import com.example.cricket.cache.MatchCache;
import com.example.cricket.dto.*;
import com.example.cricket.exception.InvalidMatchStateException;
import com.example.cricket.exception.MatchNotFoundException;
import com.example.cricket.model.*;
import com.example.cricket.repository.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;

/**
 * Match lifecycle and ball-by-ball ingestion.
 *
 * Idempotency: every accepted delivery carries an eventId; a unique
 * (match_id, event_id) constraint guarantees a retried submission can never
 * be counted twice - the service returns the current state with duplicate=true.
 *
 * Caching: the latest match state per match is kept in Redis (write-through
 * via getState, evicted inside the ingestion transaction so a stale state can
 * never be served after a new ball).
 */
@Service
public class MatchService {

    private static final Logger log = LoggerFactory.getLogger(MatchService.class);

    private final MatchRepository matchRepository;
    private final InningsRepository inningsRepository;
    private final DeliveryRepository deliveryRepository;
    private final PredictionRepository predictionRepository;
    private final MatchCache matchCache;

    public MatchService(MatchRepository matchRepository,
                        InningsRepository inningsRepository,
                        DeliveryRepository deliveryRepository,
                        PredictionRepository predictionRepository,
                        MatchCache matchCache) {
        this.matchRepository = matchRepository;
        this.inningsRepository = inningsRepository;
        this.deliveryRepository = deliveryRepository;
        this.predictionRepository = predictionRepository;
        this.matchCache = matchCache;
    }

    // ------------------------------------------------------------------ CRUD

    @Transactional
    public MatchResponse createMatch(CreateMatchRequest request) {
        if (request.team1().equalsIgnoreCase(request.team2())) {
            throw new InvalidMatchStateException("team1 and team2 must be different");
        }
        Match match = matchRepository.save(new Match(request.team1(), request.team2()));
        // First innings: team1 bats
        inningsRepository.save(new Innings(match.getId(), 1, request.team1(), request.team2(), null));
        log.info("Created match {} ({} vs {})", match.getId(), request.team1(), request.team2());
        return MatchResponse.from(match);
    }

    @Transactional(readOnly = true)
    public List<MatchResponse> listLive() {
        return matchRepository.findByStatusOrderByUpdatedAtDesc(Match.STATUS_LIVE).stream()
                .map(MatchResponse::from)
                .toList();
    }

    @Transactional(readOnly = true)
    public MatchResponse getMatch(Long id) {
        return MatchResponse.from(requireMatch(id));
    }

    @Transactional(readOnly = true)
    public MatchStateResponse getState(Long id) {
        Match match = requireMatch(id);
        Innings innings = requireCurrentInnings(match);
        MatchStateResponse state = toState(match, innings);
        // Write-through cache read (no-op when Redis is down)
        matchCache.putState(state);
        return state;
    }

    @Transactional(readOnly = true)
    public List<PredictionResultResponse> getPredictions(Long id) {
        requireMatch(id);
        long liveVersion = requireMatch(id).getStateVersion();
        return predictionRepository.findTop50ByMatchIdOrderByCreatedAtDesc(id).stream()
                .map(p -> toPredictionResponse(p, liveVersion))
                .toList();
    }

    // ------------------------------------------------------------- ingestion

    /** Outcome of an ingestion attempt (accepted or duplicate). */
    public record IngestResult(boolean duplicate, Match match, Innings innings) {
    }

    /**
     * Apply one ball event to the match state. Transactional: the delivery,
     * innings totals and match version commit together or not at all.
     */
    @Transactional
    public IngestResult ingestBall(Long matchId, BallEventRequest event) {
        Match match = requireMatch(matchId);
        if (Match.STATUS_COMPLETED.equals(match.getStatus())) {
            throw new InvalidMatchStateException("Match " + matchId + " is already completed");
        }

        String eventId = (event.eventId() != null && !event.eventId().isBlank())
                ? event.eventId()
                : defaultEventId(matchId, event);

        // --- idempotency: already accepted? ---------------------------------
        if (deliveryRepository.findByMatchIdAndEventId(matchId, eventId).isPresent()) {
            log.info("Duplicate ball event ignored: match={} event={}", matchId, eventId);
            return new IngestResult(true, match, requireCurrentInnings(match));
        }

        // --- resolve target innings -----------------------------------------
        Innings innings = resolveInnings(match, event.inning());

        // --- apply the ball --------------------------------------------------
        innings.setRuns(innings.getRuns() + event.runs());
        innings.setBallsBowled(innings.getBallsBowled() + 1);
        if (event.wicket()) {
            innings.setWickets(innings.getWickets() + 1);
        }

        boolean allOut = innings.getWickets() >= 10;
        boolean oversDone = innings.getBallsBowled() >= 120;
        boolean chasedDown = innings.getInningNumber() == 2 && innings.getTarget() != null
                && innings.getRuns() >= innings.getTarget();

        if (allOut || oversDone || chasedDown) {
            innings.setCompleted(true);
            if (innings.getInningNumber() == 1) {
                // First innings over: open the chase with target = total + 1
                match.setCurrentInnings(2);
            } else {
                match.setStatus(Match.STATUS_COMPLETED);
            }
        }

        match.setStateVersion(match.getStateVersion() + 1);
        match.setUpdatedAt(Instant.now());

        // Drop the cached state BEFORE commit: any concurrent reader that
        // misses the cache reads the DB (old state until commit, then fresh).
        matchCache.evictState(matchId);

        matchRepository.save(match);
        inningsRepository.save(innings);
        deliveryRepository.save(new Delivery(
                matchId, innings.getId(), eventId,
                event.over(), event.ball(),
                event.striker(), event.nonStriker(), event.bowler(),
                event.runs(), event.wicket(), match.getStateVersion()));

        log.info("Accepted ball: match={} event={} {}/{} over={} ball={} runs={} wicket={} version={}",
                matchId, eventId, innings.getRuns(), innings.getWickets(),
                event.over(), event.ball(), event.runs(), event.wicket(), match.getStateVersion());

        return new IngestResult(false, match, innings);
    }

    // -------------------------------------------------------------- helpers

    private Innings resolveInnings(Match match, int requestedInning) {
        Innings current = inningsRepository
                .findByMatchIdAndInningNumber(match.getId(), requestedInning)
                .orElse(null);

        if (current == null) {
            if (requestedInning == 1) {
                // Defensive: match creation always opens innings 1
                current = inningsRepository.save(
                        new Innings(match.getId(), 1, match.getTeam1(), match.getTeam2(), null));
            } else if (requestedInning == 2 && match.getCurrentInnings() >= 2) {
                Innings first = inningsRepository
                        .findByMatchIdAndInningNumber(match.getId(), 1)
                        .orElseThrow(() -> new InvalidMatchStateException(
                                "Cannot open second innings: first-innings total unknown"));
                Integer target = first.getRuns() + 1;
                current = inningsRepository.save(
                        new Innings(match.getId(), 2, match.getTeam2(), match.getTeam1(), target));
                first.setCompleted(true);
                inningsRepository.save(first);
            } else {
                throw new InvalidMatchStateException(
                        "Innings " + requestedInning + " is not open for match " + match.getId());
            }
        } else if (current.isCompleted()) {
            throw new InvalidMatchStateException(
                    "Innings " + requestedInning + " of match " + match.getId() + " is already completed");
        }
        return current;
    }

    private Match requireMatch(Long id) {
        return matchRepository.findById(id)
                .orElseThrow(() -> new MatchNotFoundException(id));
    }

    private Innings requireCurrentInnings(Match match) {
        return inningsRepository
                .findByMatchIdAndInningNumber(match.getId(), match.getCurrentInnings())
                .orElseThrow(() -> new InvalidMatchStateException(
                        "No state yet for match " + match.getId()));
    }

    private static String defaultEventId(Long matchId, BallEventRequest e) {
        return "m" + matchId + ":i" + e.inning() + ":o" + e.over() + ":b" + e.ball();
    }

    /** Cricket decimal overs: 36 balls -> 6.0, 39 balls -> 6.3. */
    public static double toOvers(int ballsBowled) {
        return (ballsBowled / 6) + (ballsBowled % 6) / 10.0;
    }

    public static MatchStateResponse toState(Match match, Innings innings) {
        int ballsRemaining = 120 - innings.getBallsBowled();
        return new MatchStateResponse(
                match.getId(),
                innings.getInningNumber(),
                innings.getBattingTeam(),
                innings.getBowlingTeam(),
                toOvers(innings.getBallsBowled()),
                innings.getRuns(),
                innings.getWickets(),
                innings.getBallsBowled(),
                ballsRemaining,
                innings.getTarget(),
                match.getStateVersion());
    }

    public static PredictionResultResponse toPredictionResponse(Prediction p, long liveVersion) {
        return new PredictionResultResponse(
                p.getId(), p.getMatchId(), p.getInning(), p.getStateVersion(),
                p.getModelType(), p.getWinProbability(), p.getPredictedScore(),
                p.getLatencyMs(), p.getCreatedAt(),
                p.getStateVersion() < liveVersion);
    }
}
