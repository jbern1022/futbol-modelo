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
    api_football_id INT UNIQUE,
    nfl_abbr        TEXT UNIQUE, -- nfl_data_py's own team_abbr, e.g. 'KC', 'SF'
    nba_team_id     BIGINT UNIQUE, -- nba_api's own numeric team id
    -- upsert_team()'s ON CONFLICT (name) DO NOTHING (src/ingestion/loader.py)
    -- requires this constraint to function at all -- without it, every
    -- team upsert throws "no unique or exclusion constraint matching
    -- the ON CONFLICT specification". See sql/fix_duplicate_teams.sql
    -- for the real incident this constraint's absence originally caused.
    CONSTRAINT teams_name_unique UNIQUE (name)
);

-- Weather-as-a-feature prerequisite: city-level venue coordinates,
-- sourced from API-Football's venue.city geocoded via Open-Meteo (no
-- key required). See sql/migrations/0021_team_venues.sql and
-- scripts/backfill_team_venues.py.
CREATE TABLE IF NOT EXISTS team_venues (
    team_id     INT PRIMARY KEY REFERENCES teams(team_id),
    venue_name  TEXT,
    city        TEXT,
    country     TEXT,
    latitude    NUMERIC(8,5),
    longitude   NUMERIC(8,5),
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE players (
    player_id       SERIAL PRIMARY KEY,
    full_name       TEXT NOT NULL,
    birth_date      DATE,
    position        TEXT,                          -- GK/DF/MF/FW
    fbref_id        TEXT UNIQUE,
    understat_id    TEXT UNIQUE,
    api_football_id INT UNIQUE,
    nba_player_id   BIGINT UNIQUE,
    nfl_player_id   TEXT UNIQUE -- nflverse's gsis_id, e.g. '00-0034857'
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
    referee         TEXT,                          -- normalized name, see 0033
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
    snap_pct            NUMERIC(5,2),                 -- share of offensive snaps -- the
                                                       -- real usage signal a rolling
                                                       -- yardage average alone can't see
    PRIMARY KEY (match_id, player_id)
);

-- NBA player points props' only feature source -- a rolling window
-- over these rows, computed live at slate-generation time (see
-- scripts/generate_nba_slate.py), not a persisted/trained model.
CREATE TABLE player_match_stats_nba (
    match_id   INT NOT NULL REFERENCES matches(match_id),
    player_id  INT NOT NULL REFERENCES players(player_id),
    team_id    INT NOT NULL REFERENCES teams(team_id),
    minutes    NUMERIC(5,1),
    points     INT,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX idx_player_match_stats_nba_player ON player_match_stats_nba (player_id);

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

-- Retention: rows older than the last 3 completed seasons per league
-- get moved here by scripts/archive_old_shots.py, not deleted -- this
-- data feeds the planned custom xG model. See
-- sql/migrations/0009_shots_archive.sql.
CREATE TABLE IF NOT EXISTS shots_archive (
    shot_id         BIGINT PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    player_id       INT REFERENCES players(player_id),
    team_id         INT REFERENCES teams(team_id),
    minute          INT,
    x               NUMERIC(6,4),
    y               NUMERIC(6,4),
    situation       TEXT,
    body_part       TEXT,
    result          TEXT,
    source_xg       NUMERIC(6,4),
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Storage half of the real bookmaker odds comparison feature -- one
-- row per (match, bookmaker, market, selection), latest snapshot only
-- (ON CONFLICT updates in place). See
-- sql/migrations/0010_match_odds.sql and
-- src/ingestion/api_football.py's fetch_and_store_odds().
CREATE TABLE IF NOT EXISTS match_odds (
    odds_id             BIGSERIAL PRIMARY KEY,
    match_id            INT NOT NULL REFERENCES matches(match_id),
    bookmaker_id        INT,
    bookmaker_name      TEXT,
    market              TEXT NOT NULL,
    selection           TEXT NOT NULL,
    -- Nullable, best-effort only -- see sql/migrations/0029's comment.
    -- Player-market odds (e.g. Anytime Goal Scorer) give a bare name
    -- string, not an api_football_id, unlike every other player
    -- reference in this schema.
    player_id           INT REFERENCES players(player_id),
    decimal_odds        NUMERIC(8,3) NOT NULL,
    implied_probability NUMERIC(6,5),
    no_vig_probability  NUMERIC(6,5),
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, bookmaker_id, market, selection)
);

CREATE INDEX IF NOT EXISTS idx_match_odds_match ON match_odds(match_id);

-- Append-only odds history (match_odds itself upserts, latest snapshot
-- only) -- opening/closing-line movement analysis. See
-- sql/migrations/0019_match_odds_history.sql.
CREATE TABLE IF NOT EXISTS match_odds_history (
    odds_history_id      BIGSERIAL PRIMARY KEY,
    match_id             INT NOT NULL REFERENCES matches(match_id),
    bookmaker_id          INT,
    bookmaker_name        TEXT,
    market                TEXT NOT NULL,
    selection             TEXT NOT NULL,
    player_id             INT REFERENCES players(player_id),
    decimal_odds          NUMERIC(8,3) NOT NULL,
    implied_probability   NUMERIC(6,5),
    no_vig_probability    NUMERIC(6,5),
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_match_odds_history_match
    ON match_odds_history(match_id, bookmaker_id, market, selection, fetched_at);

CREATE OR REPLACE VIEW v_odds_movement AS
SELECT
    o.match_id, o.bookmaker_id, o.bookmaker_name, o.market, o.selection,
    o.decimal_odds AS opening_odds, o.no_vig_probability AS opening_probability,
    o.fetched_at AS opening_fetched_at,
    c.decimal_odds AS closing_odds, c.no_vig_probability AS closing_probability,
    c.fetched_at AS closing_fetched_at,
    o.player_id
FROM (
    SELECT DISTINCT ON (match_id, bookmaker_id, market, selection)
        match_id, bookmaker_id, bookmaker_name, market, selection, player_id,
        decimal_odds, no_vig_probability, fetched_at
    FROM match_odds_history
    ORDER BY match_id, bookmaker_id, market, selection, fetched_at ASC
) o
JOIN (
    SELECT DISTINCT ON (match_id, bookmaker_id, market, selection)
        match_id, bookmaker_id, market, selection,
        decimal_odds, no_vig_probability, fetched_at
    FROM match_odds_history
    ORDER BY match_id, bookmaker_id, market, selection, fetched_at DESC
) c USING (match_id, bookmaker_id, market, selection);

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
                        '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT', 'CARDS',
                        'PLAYER_GOALS', 'PLAYER_SAVES',
                        -- NFL (live) -- neither NFL nor NBA has a draw,
                        -- so 1X2 doesn't apply; MONEYLINE is the 2-way
                        -- equivalent, SPREAD is a handicap on signed
                        -- margin, not an O/U on a count
                        'MONEYLINE', 'SPREAD', 'TOTAL_POINTS',
                        'PLAYER_PASS_YARDS', 'PLAYER_RUSH_YARDS',
                        'PLAYER_RECEIVING_YARDS', 'PLAYER_RECEPTIONS', 'PLAYER_ANYTIME_TD',
                        -- NBA (live)
                        'PLAYER_POINTS')),
    subject_team_id INT REFERENCES teams(team_id),
    subject_player_id INT REFERENCES players(player_id),
    statement       TEXT NOT NULL,   -- human-readable: 'Inter over 5.5 corners'
    line            NUMERIC(6,2),    -- threshold where applicable (5.5, 2.5, ...)
    side            TEXT,            -- 'over'|'under'|'home'|'draw'|'away'|'yes'|'no'
    probability     NUMERIC(6,5) NOT NULL CHECK (probability > 0 AND probability < 1),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    context         JSONB            -- form inputs the model saw (last-5 rolling
                                      -- stats, rest days, etc), for the "why"
                                      -- panel. Nullable -- only props markets
                                      -- populate it; older rows predate it.
);
CREATE INDEX idx_predictions_match ON predictions (match_id);
CREATE INDEX idx_predictions_market ON predictions (market);
-- Backs persist_slate()'s ON CONFLICT DO NOTHING -- one prediction per
-- (fixture, model version, market/side/line/subject), so a re-run only
-- inserts genuinely new rows. See sql/migrations/0002_track_predictions_natural_key.sql.
CREATE UNIQUE INDEX predictions_natural_key ON predictions (
    match_id, model_version_id, market,
    COALESCE(subject_team_id, '-1'::integer),
    COALESCE(subject_player_id, '-1'::integer),
    COALESCE(side, ''::text),
    COALESCE(line, '-9999'::integer::numeric)
);

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

-- Append-only, same discipline as predictions above. The PRIMARY KEY
-- already stops a second INSERT for the same prediction; this stops a
-- raw UPDATE/DELETE from silently rewriting an existing grade instead.
-- See sql/migrations/0007_lock_prediction_grades.sql.
CREATE OR REPLACE FUNCTION forbid_grade_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'prediction_grades are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_prediction_grades_no_update
    BEFORE UPDATE OR DELETE ON prediction_grades
    FOR EACH ROW EXECUTE FUNCTION forbid_grade_mutation();

-- ---------- Season report views ----------

-- Dedupes by natural key (earliest prediction_id per match/market/side/
-- line/subject wins) before anything gets aggregated, so a fixture that
-- somehow got slated twice can't double-count in the views below without
-- touching the ledger itself -- every row still exists in `predictions`
-- exactly as inserted. See sql/migrations/0003_dedupe_scorecard_views.sql.
CREATE OR REPLACE VIEW v_graded_predictions AS
SELECT prediction_id, match_id, market, side, line, subject_team_id,
       subject_player_id, probability, outcome, league, season, sport
FROM (
    SELECT p.prediction_id, p.match_id, p.market, p.side, p.line,
           p.subject_team_id, p.subject_player_id, p.probability,
           g.outcome, l.code AS league, s.label AS season, l.sport AS sport,
           ROW_NUMBER() OVER (
               PARTITION BY p.match_id, p.market, p.side, p.line,
                            p.subject_team_id, p.subject_player_id
               ORDER BY p.prediction_id
           ) AS rn
    FROM predictions p
    JOIN prediction_grades g USING (prediction_id)
    JOIN matches m USING (match_id)
    JOIN seasons s USING (season_id)
    JOIN leagues l USING (league_id)
    WHERE g.outcome <> 'void'
) ranked
WHERE rn = 1;

CREATE OR REPLACE VIEW v_calibration AS
SELECT
    market,
    league,
    width_bucket(probability, 0.0, 1.0, 10) AS prob_bucket,      -- decile bins
    ROUND(AVG(probability)::numeric, 4)     AS avg_stated_prob,
    ROUND(AVG((outcome = 'hit')::int)::numeric, 4) AS realized_rate,
    COUNT(*) AS n,
    side,
    sport
FROM v_graded_predictions
GROUP BY market, side, league, prob_bucket, sport;

CREATE OR REPLACE VIEW v_season_scorecard AS
SELECT
    league,
    season,
    market,
    COUNT(*)                                        AS n_predictions,
    ROUND(AVG((outcome='hit')::int)::numeric, 4)    AS hit_rate,
    ROUND(AVG(probability)::numeric, 4)             AS avg_confidence,
    -- Brier score: mean squared error of probability vs outcome
    ROUND(AVG(POWER(probability - (outcome='hit')::int, 2))::numeric, 4) AS brier,
    -- Log loss (clamped)
    ROUND(AVG(
        - ( (outcome='hit')::int * LN(GREATEST(probability, 1e-9))
          + (1-(outcome='hit')::int) * LN(GREATEST(1-probability, 1e-9)) )
    )::numeric, 4)                                  AS log_loss,
    sport
FROM v_graded_predictions
GROUP BY league, season, market, sport
ORDER BY league, season, market;

-- UI half of the real bookmaker odds comparison -- backs
-- /v1/odds-comparison and the Track Record page's market comparison
-- section. Not gated on grading (unlike v_calibration/v_season_scorecard):
-- match_odds is fetched for still-scheduled fixtures, so this is mostly
-- pre-game model estimate vs pre-game market estimate; rows survive
-- past kickoff untouched, so already-graded matches show up here too
-- once enough time passes. See sql/migrations/0011_market_comparison_view.sql.
CREATE OR REPLACE VIEW v_market_comparison AS
SELECT
    l.code            AS league,
    m.match_id,
    th.name           AS home_team,
    ta.name           AS away_team,
    m.kickoff_utc,
    m.status,
    p.side,
    p.probability                                 AS model_probability,
    ROUND(AVG(mo.no_vig_probability)::numeric, 4)  AS market_probability,
    COUNT(DISTINCT mo.bookmaker_id)                AS n_bookmakers
FROM (
    SELECT p.*, ROW_NUMBER() OVER (
        PARTITION BY p.match_id, p.market, p.side, p.line,
                     p.subject_team_id, p.subject_player_id
        ORDER BY p.prediction_id
    ) AS rn
    FROM predictions p
    WHERE p.market = '1X2'
) p
JOIN matches m ON m.match_id = p.match_id
JOIN teams th ON th.team_id = m.home_team_id
JOIN teams ta ON ta.team_id = m.away_team_id
JOIN seasons s ON s.season_id = m.season_id
JOIN leagues l ON l.league_id = s.league_id
JOIN match_odds mo ON mo.match_id = m.match_id AND LOWER(mo.selection) = p.side
WHERE p.rn = 1
GROUP BY l.code, m.match_id, th.name, ta.name, m.kickoff_utc, m.status, p.side, p.probability;

-- Petey v2 (docs/petey-spec.md, ADR-003): the one fixed, safe base query
-- the JSON filter compiler is ever allowed to add a WHERE clause to.
-- Per-prediction, not pre-aggregated -- Petey computes n/avg_confidence/
-- hit_rate over whatever this filters down to, same never-show-Ollama-
-- raw-rows pattern /v1/ask already uses. See sql/migrations/0017_petey_v2.sql.
CREATE OR REPLACE VIEW v_petey_predictions AS
SELECT
    gp.prediction_id,
    gp.market,
    gp.league,
    gp.season,
    gp.side,
    gp.probability,
    gp.outcome,
    t.name AS team,
    m.kickoff_utc::date AS kickoff_date
FROM v_graded_predictions gp
JOIN matches m ON m.match_id = gp.match_id
LEFT JOIN teams t ON t.team_id = gp.subject_team_id;

-- Logs every free-text Petey question alongside the JSON filter Ollama
-- proposed for it, per the spec's self-improving FAQ loop.
CREATE TABLE IF NOT EXISTS petey_queries (
    query_id     SERIAL PRIMARY KEY,
    raw_text     TEXT NOT NULL,
    compiled_filter JSONB,          -- NULL if validation rejected Ollama's proposal
    rejected_reason TEXT,           -- set iff compiled_filter IS NULL
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ingest review queue (entity-resolution items needing human eyes)
CREATE TABLE IF NOT EXISTS ingest_review (
    review_id   SERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,
    detail      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Candidates build_slate() drops because probability rounded to exactly
-- 0 or 1 (predictions.probability's CHECK would reject them) -- makes
-- an otherwise-silent skip queryable. See
-- sql/migrations/0008_degenerate_prediction_skips.sql.
CREATE TABLE IF NOT EXISTS degenerate_prediction_skips (
    skip_id            BIGSERIAL PRIMARY KEY,
    match_id           INT NOT NULL REFERENCES matches(match_id),
    market             TEXT NOT NULL,
    statement          TEXT NOT NULL,
    side               TEXT,
    line               NUMERIC(6,2),
    subject_team_id    INT REFERENCES teams(team_id),
    subject_player_id  INT REFERENCES players(player_id),
    raw_probability    DOUBLE PRECISION NOT NULL,
    detected_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_degenerate_skips_match ON degenerate_prediction_skips(match_id);

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

-- Tracks which sql/migrations/*.sql files have been applied -- see
-- sql/migrations/README.md and scripts/migrate.py.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Backtesting ----------

-- Paper-trading / bankroll simulation -- see sql/migrations/0030.
-- Full-recompute, not append-only: scripts/simulate_bankroll.py
-- truncates and rewrites this every run.
CREATE TABLE IF NOT EXISTS bankroll_simulation (
    prediction_id     BIGINT PRIMARY KEY REFERENCES predictions(prediction_id),
    match_id          INT NOT NULL REFERENCES matches(match_id),
    kickoff_utc       TIMESTAMPTZ NOT NULL,
    market            TEXT NOT NULL,
    side              TEXT NOT NULL,
    model_probability NUMERIC(6,5) NOT NULL,
    decimal_odds      NUMERIC(8,3) NOT NULL,
    stake             NUMERIC(10,2) NOT NULL,
    outcome           TEXT NOT NULL,
    profit            NUMERIC(10,2) NOT NULL,
    bankroll_after    NUMERIC(12,2) NOT NULL,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bankroll_simulation_kickoff
    ON bankroll_simulation(kickoff_utc);

-- Bootstrap CIs on Dixon-Coles attack/defence ratings -- see
-- sql/migrations/0031 and src/models/team_ratings.py. Full-recompute,
-- a current snapshot (not per-season, unlike home_advantage_history).
CREATE TABLE IF NOT EXISTS team_ratings (
    league          TEXT NOT NULL,
    team            TEXT NOT NULL,
    atk             NUMERIC(6,4) NOT NULL,
    atk_ci_low      NUMERIC(6,4) NOT NULL,
    atk_ci_high     NUMERIC(6,4) NOT NULL,
    dfn             NUMERIC(6,4) NOT NULL,
    dfn_ci_low      NUMERIC(6,4) NOT NULL,
    dfn_ci_high     NUMERIC(6,4) NOT NULL,
    n_boot_samples  INT NOT NULL,
    n_matches       INT NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league, team)
);
