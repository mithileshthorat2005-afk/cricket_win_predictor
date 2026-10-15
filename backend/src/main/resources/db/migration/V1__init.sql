-- ============================================================
-- V1: initial schema for the cricket win-probability orchestrator
-- Portable across MySQL 8 (prod) and H2 in MySQL mode (tests)
-- ============================================================

CREATE TABLE matches (
    id               BIGINT       NOT NULL AUTO_INCREMENT,
    team1            VARCHAR(128) NOT NULL,
    team2            VARCHAR(128) NOT NULL,
    status           VARCHAR(16)  NOT NULL DEFAULT 'LIVE',
    current_innings  INT          NOT NULL DEFAULT 1,
    state_version    BIGINT       NOT NULL DEFAULT 0,
    created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id)
);

CREATE INDEX idx_matches_status ON matches (status);

CREATE TABLE innings (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    match_id      BIGINT       NOT NULL,
    inning_number INT          NOT NULL,
    batting_team  VARCHAR(128) NOT NULL,
    bowling_team  VARCHAR(128) NOT NULL,
    runs          INT          NOT NULL DEFAULT 0,
    wickets       INT          NOT NULL DEFAULT 0,
    balls_bowled  INT          NOT NULL DEFAULT 0,
    target        INT          NULL,
    completed     BOOLEAN      NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    CONSTRAINT uq_innings_match_inning UNIQUE (match_id, inning_number),
    CONSTRAINT fk_innings_match FOREIGN KEY (match_id) REFERENCES matches (id)
);

CREATE TABLE deliveries (
    id                  BIGINT       NOT NULL AUTO_INCREMENT,
    match_id            BIGINT       NOT NULL,
    innings_id          BIGINT       NOT NULL,
    event_id            VARCHAR(64)  NOT NULL,
    -- 'over' is a reserved word in MySQL 8 (window functions) => over_number
    over_number         INT          NOT NULL,
    ball                INT          NOT NULL,
    striker             VARCHAR(64)  NOT NULL,
    non_striker         VARCHAR(64)  NULL,
    bowler              VARCHAR(64)  NOT NULL,
    runs                INT          NOT NULL,
    wicket              BOOLEAN      NOT NULL DEFAULT FALSE,
    state_version_after BIGINT       NOT NULL,
    created_at          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    -- Idempotency: the same delivery can never be counted twice
    CONSTRAINT uq_deliveries_match_event UNIQUE (match_id, event_id),
    CONSTRAINT fk_deliveries_match FOREIGN KEY (match_id) REFERENCES matches (id),
    CONSTRAINT fk_deliveries_innings FOREIGN KEY (innings_id) REFERENCES innings (id)
);

CREATE INDEX idx_deliveries_match_innings ON deliveries (match_id, innings_id);

CREATE TABLE predictions (
    id               BIGINT        NOT NULL AUTO_INCREMENT,
    match_id         BIGINT        NOT NULL,
    inning           INT           NOT NULL,
    state_version    BIGINT        NOT NULL,
    model_type       VARCHAR(16)   NOT NULL,
    -- NULL for first-innings montecarlo score predictions (no win probability)
    win_probability  DOUBLE        NULL,
    predicted_score  DOUBLE        NULL,
    latency_ms       BIGINT        NOT NULL,
    created_at       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    CONSTRAINT fk_predictions_match FOREIGN KEY (match_id) REFERENCES matches (id)
);

CREATE INDEX idx_predictions_match_version ON predictions (match_id, state_version);
CREATE INDEX idx_predictions_match_created ON predictions (match_id, created_at);
