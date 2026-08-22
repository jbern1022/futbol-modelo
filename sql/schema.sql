-- =============================================================
-- Bernal Labs :: futbol-modelo — Postgres schema v1
-- Leagues covered at launch: Premier League, Serie A
-- International module (World Cup) reuses same tables via league dimension
-- =============================================================

CREATE SCHEMA IF NOT EXISTS futbol;
SET search_path TO futbol;

-- ---------- Dimensions ----------

CREATE TABLE leagues (
    league_id       SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,          -- 'EPL', 'SERIE_A', 'WC'
    name            TEXT NOT NULL,
    is_international BOOLEAN NOT NULL DEFAULT FALSE,
    sport           TEXT NOT NULL DEFAULT 'soccer'
                    CHECK (sport IN ('soccer', 'basketball', 'football'))
);

CREATE TABLE seasons (
    season_id       SERIAL PRIMARY KEY,
    league_id       INT NOT NULL REFERENCES leagues(league_id),
    label           TEXT NOT NULL,                 -- '2026-27', 'WC2026'
    start_date      DATE,
    end_date        DATE,
    UNIQUE (league_id, label)
);

CREATE TABLE teams (
    team_id         SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    country         TEXT,
    is_national     BOOLEAN NOT NULL DEFAULT FALSE,
    -- external ids for ingestion joins
    fbref_id        TEXT UNIQUE,
    understat_id    TEXT UNIQUE,
    api_football_id INT UNIQUE
);

CREATE TABLE players (
    player_id       SERIAL PRIMARY KEY,
    full_name       TEXT NOT NULL,
    birth_date      DATE,
    position        TEXT,                          -- GK/DF/MF/FW
    fbref_id        TEXT UNIQUE,
    understat_id    TEXT UNIQUE,
    api_football_id INT UNIQUE
);

-- ---------- Facts ----------

CREATE TABLE matches (
    match_id        SERIAL PRIMARY KEY,
    season_id       INT NOT NULL REFERENCES seasons(season_id),
    home_team_id    INT NOT NULL REFERENCES teams(team_id),
    away_team_id    INT NOT NULL REFERENCES teams(team_id),
    kickoff_utc     TIMESTAMPTZ NOT NULL,
    stage           TEXT,                          -- 'league', 'group', 'R16', 'QF'...
    status          TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled|live|final|postponed
    home_score      INT,
    away_score      INT,
    went_to_ot      BOOLEAN DEFAULT FALSE,
    went_to_pens    BOOLEAN DEFAULT FALSE,
    pens_home       INT,
    pens_away       INT,
    external_ref    TEXT,                          -- source event id
    UNIQUE (season_id, home_team_id, away_team_id, kickoff_utc)
);
CREATE INDEX idx_matches_kickoff ON matches (kickoff_utc);
-- Partial (nullable-safe) unique index: a kickoff-time correction
-- between ingestion runs must update the existing row for a fixture,
-- not insert a duplicate. Ingestion code looks this up explicitly
-- before falling back to the natural key above (see api_football.py's
-- backfill_primary()) -- found live as a real, active bug (9 duplicate
-- fixtures, 139 predictions that could never be graded).
CREATE UNIQUE INDEX idx_matches_external_ref ON matches (external_ref) WHERE external_ref IS NOT NULL;
CREATE INDEX idx_matches_status  ON matches (status);

CREATE TABLE team_match_stats (
    match_id        INT NOT NULL REFERENCES matches(match_id),
    team_id         INT NOT NULL REFERENCES teams(team_id),
    is_home         BOOLEAN NOT NULL,
    xg              NUMERIC(6,3),
    shots           INT,
    shots_on_target INT,
    corners         INT,
    possession_pct  NUMERIC(5,2),
    fouls           INT,
    yellows         INT,
    reds            INT,
    saves           INT,
    ppda            NUMERIC(6,2),                  -- pressing intensity (Understat)
    deep_completions INT,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE player_match_stats (
    match_id        INT NOT NULL REFERENCES matches(match_id),
    player_id       INT NOT NULL REFERENCES players(player_id),
    team_id         INT NOT NULL REFERENCES teams(team_id),
    minutes         INT,
    goals           INT DEFAULT 0,
    assists         INT DEFAULT 0,
    shots           INT DEFAULT 0,
    shots_on_target INT DEFAULT 0,
    xg              NUMERIC(6,3),
    xa              NUMERIC(6,3),
    key_passes      INT DEFAULT 0,
    saves           INT,                           -- GK only
    goals_conceded  INT,                           -- GK only
    PRIMARY KEY (match_id, player_id)
);

-- ---------- NFL stats (per-sport tables per 2026-08-21 decision: the
-- soccer stat tables above don't generalize, per-sport tables keep full
-- type safety and easy indexing over a shared JSONB blob). matches/teams/
-- players/leagues/seasons stay shared -- only the stat shape is soccer-
-- specific. Column list is a best-effort standard NFL box-score set
-- (matches what nflverse/nfl_data_py exposes); expect adjustment once the
-- actual NFL ingestion adapter is built and its real field names are known.

CREATE TABLE team_match_stats_nfl (
    match_id            INT NOT NULL REFERENCES matches(match_id),
    team_id             INT NOT NULL REFERENCES teams(team_id),
    is_home             BOOLEAN NOT NULL,
    total_yards         INT,
    passing_yards       INT,
    rushing_yards       INT,
    turnovers           INT,
    sacks_allowed       INT,
    sacks_made          INT,
    penalties           INT,
    penalty_yards       INT,
    first_downs         INT,
    third_down_attempts INT,
    third_down_conversions INT,
    time_of_possession_seconds INT,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE player_match_stats_nfl (
    match_id            INT NOT NULL REFERENCES matches(match_id),
    player_id           INT NOT NULL REFERENCES players(player_id),
    team_id             INT NOT NULL REFERENCES teams(team_id),
    position            TEXT,                       -- 'QB','RB','WR','TE',...
    passing_attempts    INT,
    passing_completions INT,
    passing_yards       INT,
    passing_tds         INT,
    interceptions_thrown INT,
    rushing_attempts    INT,
    rushing_yards       INT,
    rushing_tds         INT,
    targets             INT,
    receptions          INT,
    receiving_yards     INT,
    receiving_tds       INT,
    tackles             INT,                         -- defense
    sacks               NUMERIC(3,1),                 -- defense; half-sacks are real
    PRIMARY KEY (match_id, player_id)
);

-- Event-level shots (Understat) — feeds the custom xG model later (v3)
CREATE TABLE shots (
    shot_id         BIGSERIAL PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    player_id       INT REFERENCES players(player_id),
    team_id         INT REFERENCES teams(team_id),
    minute          INT,
    x               NUMERIC(6,4),                  -- Understat normalized coords
    y               NUMERIC(6,4),
    situation       TEXT,                          -- OpenPlay|SetPiece|Corner|Penalty...
    body_part       TEXT,
    result          TEXT,                          -- Goal|SavedShot|MissedShots|BlockedShot|Post
    source_xg       NUMERIC(6,4)                   -- Understat's xG, our benchmark
);

-- ---------- Model registry ----------

CREATE TABLE model_versions (
    model_version_id SERIAL PRIMARY KEY,
    model_name      TEXT NOT NULL,                 -- 'dixon_coles', 'props_corners_lgbm'
    version_tag     TEXT NOT NULL,                 -- git sha or semver
    trained_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    training_window TEXT,                          -- '2021-08-01..2026-06-30'
    params          JSONB,
    train_metrics   JSONB,
    UNIQUE (model_name, version_tag)
);

-- ---------- THE PREDICTION LEDGER (crown jewel) ----------
-- Rules enforced by design:
--   1. Predictions insert-only. No UPDATE of probability/statement ever.
--   2. locked_at must precede kickoff — enforced by trigger.
--   3. Grading lives in a separate table; the prediction row is never touched.

CREATE TABLE predictions (
    prediction_id   BIGSERIAL PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    model_version_id INT NOT NULL REFERENCES model_versions(model_version_id),
    market          TEXT NOT NULL CHECK (market IN (
                        -- soccer (live)
                        '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT',
                        'PLAYER_GOALS', 'PLAYER_SAVES',
                        -- NFL/NBA (schema prep only -- nothing writes these
                        -- yet; neither sport has a draw, so 1X2 doesn't
                        -- apply, MONEYLINE is the 2-way equivalent, SPREAD
                        -- is a handicap on signed margin, not an O/U on a
                        -- count)
                        'MONEYLINE', 'SPREAD', 'TOTAL_POINTS')),
    subject_team_id INT REFERENCES teams(team_id),
    subject_player_id INT REFERENCES players(player_id),
    statement       TEXT NOT NULL,   -- human-readable: 'Inter over 5.5 corners'
    line            NUMERIC(6,2),    -- threshold where applicable (5.5, 2.5, ...)
    side            TEXT,            -- 'over'|'under'|'home'|'draw'|'away'|'yes'|'no'
    probability     NUMERIC(6,5) NOT NULL CHECK (probability > 0 AND probability < 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_predictions_match ON predictions (match_id);
CREATE INDEX idx_predictions_market ON predictions (market);

-- Immutability + pre-kickoff enforcement
CREATE OR REPLACE FUNCTION forbid_prediction_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'predictions are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_predictions_no_update
    BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION forbid_prediction_mutation();

CREATE OR REPLACE FUNCTION enforce_pre_kickoff() RETURNS trigger AS $$
DECLARE ko TIMESTAMPTZ;
BEGIN
    SELECT kickoff_utc INTO ko FROM matches WHERE match_id = NEW.match_id;
    IF NEW.locked_at >= ko THEN
        RAISE EXCEPTION 'prediction locked after kickoff (% >= %)', NEW.locked_at, ko;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_predictions_pre_kickoff
    BEFORE INSERT ON predictions
    FOR EACH ROW EXECUTE FUNCTION enforce_pre_kickoff();

-- ---------- Grades (separate, append-only) ----------

CREATE TABLE prediction_grades (
    prediction_id   BIGINT PRIMARY KEY REFERENCES predictions(prediction_id),
    outcome         TEXT NOT NULL CHECK (outcome IN ('hit','miss','void')),
    actual_value    NUMERIC(8,3),                  -- observed stat (e.g. 7 corners)
    graded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    grader_version  TEXT NOT NULL
);

-- ---------- Season report views ----------

CREATE OR REPLACE VIEW v_calibration AS
SELECT
    p.market,
    l.code AS league,
    width_bucket(p.probability, 0.0, 1.0, 10) AS prob_bucket,      -- decile bins
    ROUND(AVG(p.probability)::numeric, 4)     AS avg_stated_prob,
    ROUND(AVG((g.outcome = 'hit')::int)::numeric, 4) AS realized_rate,
    COUNT(*) AS n
FROM predictions p
JOIN prediction_grades g USING (prediction_id)
JOIN matches m USING (match_id)
JOIN seasons s USING (season_id)
JOIN leagues l USING (league_id)
WHERE g.outcome <> 'void'
GROUP BY p.market, l.code, prob_bucket;

CREATE OR REPLACE VIEW v_season_scorecard AS
SELECT
    l.code AS league,
    s.label AS season,
    p.market,
    COUNT(*)                                            AS n_predictions,
    ROUND(AVG((g.outcome='hit')::int)::numeric, 4)      AS hit_rate,
    ROUND(AVG(p.probability)::numeric, 4)               AS avg_confidence,
    -- Brier score: mean squared error of probability vs outcome
    ROUND(AVG(POWER(p.probability - (g.outcome='hit')::int, 2))::numeric, 4) AS brier,
    -- Log loss (clamped)
    ROUND(AVG(
        - ( (g.outcome='hit')::int * LN(GREATEST(p.probability, 1e-9))
          + (1-(g.outcome='hit')::int) * LN(GREATEST(1-p.probability, 1e-9)) )
    )::numeric, 4)                                      AS log_loss
FROM predictions p
JOIN prediction_grades g USING (prediction_id)
JOIN matches m USING (match_id)
JOIN seasons s USING (season_id)
JOIN leagues l USING (league_id)
WHERE g.outcome <> 'void'
GROUP BY l.code, s.label, p.market
ORDER BY l.code, s.label, p.market;

-- Ingest review queue (entity-resolution items needing human eyes)
CREATE TABLE IF NOT EXISTS ingest_review (
    review_id   SERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,
    detail      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Pipeline run log (backing store for a freshness indicator / status page)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id        BIGSERIAL PRIMARY KEY,
    job_name      TEXT NOT NULL,       -- 'ingest-nightly','grade-nightly','predict-prematch'
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed')),
    rows_written  INT,
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_job ON pipeline_runs (job_name, started_at DESC);
