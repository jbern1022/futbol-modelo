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
    api_football_fixture_id BIGINT,                -- per-provider ids, see 0041
    understat_game_id       TEXT,
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

-- Per-provider match ids (migration 0041): external_ref holds ONE source's id, these hold each
-- provider's. A trigger keeps them filled whenever a writer sets external_ref.
CREATE UNIQUE INDEX matches_api_football_fixture_id
    ON matches (api_football_fixture_id) WHERE api_football_fixture_id IS NOT NULL;
CREATE UNIQUE INDEX matches_understat_game_id
    ON matches (understat_game_id) WHERE understat_game_id IS NOT NULL;

CREATE OR REPLACE FUNCTION sync_provider_ids() RETURNS trigger AS $$
BEGIN
    IF NEW.external_ref ~ '^api-football:\d+$' AND NEW.api_football_fixture_id IS NULL THEN
        NEW.api_football_fixture_id := substring(NEW.external_ref FROM '^api-football:(\d+)$')::bigint;
    ELSIF NEW.external_ref ~ '^understat:.+' AND NEW.understat_game_id IS NULL THEN
        NEW.understat_game_id := substring(NEW.external_ref FROM '^understat:(.+)$');
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_provider_ids
    BEFORE INSERT OR UPDATE OF external_ref ON matches
    FOR EACH ROW EXECUTE FUNCTION sync_provider_ids();

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

-- COALESCE(situation, '') matters: situation is nullable and Postgres
-- never treats two NULLs as equal in a unique index, so a plain
-- `situation` column here would silently let NULL-situation shots
-- dedupe-fail on re-ingestion (real incident: 1365 duplicate rows,
-- 100% La Liga, where NULL situation is ~6.7% of rows vs ~1% for
-- EPL/SERIE_A -- see sql/migrations/0037_fix_shots_null_situation_dedup.sql
-- and src/ingestion/loader.py's matching ON CONFLICT clause).
CREATE UNIQUE INDEX shots_natural_key ON shots (
    match_id, player_id, minute, x, y, COALESCE(situation, ''), result
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

-- Player-prop odds lookups (migration 0029).
CREATE INDEX IF NOT EXISTS idx_match_odds_player ON match_odds(player_id) WHERE player_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_odds_history_player ON match_odds_history(player_id) WHERE player_id IS NOT NULL;

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

-- Live, re-fetched injury/availability snapshot -- same shape as
-- match_odds above (a live line that can move, not a settled fact),
-- not player_match_stats (which only ever holds players who actually
-- featured in a finished match). See sql/migrations/0035 and
-- src/ingestion/api_football.py's fetch_and_store_injuries(). The
-- rolling absence-rate PRIOR derived from this (player_injury_features,
-- sql/features.sql) is what PLAYER_GOALS/PLAYER_SAVES train on and fall
-- back to at inference time when no fresh row exists here yet -- see
-- generate_slate.py.
CREATE TABLE IF NOT EXISTS player_injuries (
    match_id    INT NOT NULL REFERENCES matches(match_id),
    player_id   INT NOT NULL REFERENCES players(player_id),
    status      TEXT NOT NULL CHECK (status IN ('out', 'questionable')),
    reason      TEXT,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, player_id)
);

-- Event-level data from API-Football's /fixtures/events -- the MLS
-- equivalent of Understat's shot-level `shots` table (zero MLS
-- coverage there). See sql/migrations/0039_match_events.sql.
CREATE TABLE IF NOT EXISTS match_events (
    event_id        BIGSERIAL PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    team_id         INT REFERENCES teams(team_id),
    player_id       INT REFERENCES players(player_id),
    minute          INT NOT NULL,
    extra_minute    INT,
    type            TEXT NOT NULL,
    detail          TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS match_events_natural_key ON match_events (
    match_id, COALESCE(team_id, -1), COALESCE(player_id, -1),
    minute, COALESCE(extra_minute, -1), type, COALESCE(detail, '')
);

CREATE INDEX IF NOT EXISTS idx_match_events_match ON match_events (match_id);

-- ADR-011: in-play win-probability, continuously updated during a live
-- match -- NOT the immutable predictions ledger (that locks once
-- pre-kickoff). Full history retained (like match_odds_history, not
-- match_odds). See sql/migrations/0038_live_win_probability.sql and
-- src/predictions/live_winprob.py.
CREATE TABLE IF NOT EXISTS live_win_probability (
    id              BIGSERIAL PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    minute          INT NOT NULL,
    home_score      INT NOT NULL,
    away_score      INT NOT NULL,
    home_win_prob   NUMERIC(6,5) NOT NULL,
    draw_prob       NUMERIC(6,5) NOT NULL,
    away_win_prob   NUMERIC(6,5) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_winprob_match
    ON live_win_probability (match_id, computed_at);

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
    grader_version  TEXT NOT NULL,
    void_reason     TEXT,                          -- migration 0045; only for outcome = 'void'
    CONSTRAINT prediction_grades_void_reason_only_when_void
        CHECK (void_reason IS NULL OR outcome = 'void')
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

-- Point-in-time snapshots of each prediction's inputs. See sql/migrations/0044_prediction_snapshots.sql.
CREATE TABLE IF NOT EXISTS prediction_snapshots (
    prediction_id    BIGINT PRIMARY KEY REFERENCES predictions(prediction_id),
    schema_version   INT NOT NULL,
    cutoff_at        TIMESTAMPTZ NOT NULL,
    kickoff_at       TIMESTAMPTZ NOT NULL,
    inputs_through   TIMESTAMPTZ,
    n_games          INT,
    window_days      INT,
    model_tag        TEXT NOT NULL,
    feature_values   JSONB NOT NULL,
    missing_features TEXT[] NOT NULL DEFAULT '{}',
    referee_known    BOOLEAN,
    referee_name     TEXT,
    referee_used     TEXT,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (cutoff_at < kickoff_at),
    CHECK (inputs_through IS NULL OR inputs_through <= cutoff_at)
);

CREATE OR REPLACE FUNCTION forbid_snapshot_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'prediction_snapshots are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_prediction_snapshots_no_update
    BEFORE UPDATE OR DELETE ON prediction_snapshots
    FOR EACH ROW EXECUTE FUNCTION forbid_snapshot_mutation();

-- Per-source team stats (migrations 0025, 0040): one row per source so FBref vs API-Football can be
-- reconciled; team_match_stats holds the chosen value.
CREATE TABLE IF NOT EXISTS team_match_stats_by_source (
    match_id        INT NOT NULL REFERENCES matches(match_id),
    team_id         INT NOT NULL REFERENCES teams(team_id),
    source          TEXT NOT NULL,
    corners         INT,
    shots           INT,
    shots_on_target INT,
    fouls           INT,
    yellows         INT,
    reds            INT,
    saves           INT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    xg              NUMERIC(6,3),
    PRIMARY KEY (match_id, team_id, source)
);

-- Fitted home-advantage gamma per league and season (migration 0024).
CREATE TABLE IF NOT EXISTS home_advantage_history (
    league      TEXT NOT NULL,
    season      TEXT NOT NULL,
    gamma       DOUBLE PRECISION NOT NULL,
    n_matches   INT NOT NULL,
    fitted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league, season)
);

-- Full history of model_versions rows as they were overwritten (migration 0027).
CREATE TABLE IF NOT EXISTS model_versions_history (
    history_id      BIGSERIAL PRIMARY KEY,
    model_name      TEXT NOT NULL,
    version_tag     TEXT NOT NULL,
    training_window TEXT,
    params          JSONB,
    train_metrics   JSONB,
    trained_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_model_versions_history_name_time
    ON model_versions_history (model_name, trained_at DESC);

-- Model-governance event log. See sql/migrations/0046_model_governance_events.sql.
CREATE TABLE IF NOT EXISTS model_governance_events (
    event_id                 BIGSERIAL PRIMARY KEY,
    occurred_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    league                   TEXT NOT NULL,
    market                   TEXT NOT NULL,
    event_type               TEXT NOT NULL CHECK (event_type IN (
                                 'CHAMPION_ASSIGNED', 'CHALLENGER_REGISTERED', 'CHALLENGER_RETIRED',
                                 'PROMOTED', 'RELEGATED', 'SUSPENDED', 'ROOT_CAUSE_APPROVED')),
    model_version_id         INT REFERENCES model_versions(model_version_id),
    rollback_model_version_id INT REFERENCES model_versions(model_version_id),
    approved_by              TEXT,
    root_cause_category      TEXT,           -- free text until the owner approves a taxonomy (ADR-021)
    evidence                 JSONB NOT NULL DEFAULT '{}',
    notes                    TEXT,
    -- DB-enforced completeness. COALESCE(..., false) because a CHECK passes on NULL.
    CONSTRAINT governance_event_complete CHECK (COALESCE(CASE event_type
        WHEN 'CHAMPION_ASSIGNED'     THEN approved_by IS NOT NULL AND model_version_id IS NOT NULL
        WHEN 'CHALLENGER_REGISTERED' THEN model_version_id IS NOT NULL
        WHEN 'CHALLENGER_RETIRED'    THEN model_version_id IS NOT NULL
        WHEN 'RELEGATED'             THEN notes IS NOT NULL
        WHEN 'SUSPENDED'             THEN notes IS NOT NULL
        WHEN 'ROOT_CAUSE_APPROVED'   THEN approved_by IS NOT NULL AND root_cause_category IS NOT NULL
        WHEN 'PROMOTED'              THEN approved_by IS NOT NULL AND model_version_id IS NOT NULL
                                          AND rollback_model_version_id IS NOT NULL
                                          AND evidence ? 'head_to_head'
                                          AND CASE WHEN (evidence->>'challenger_graded_n') ~ '^[0-9]+$'
                                                   THEN (evidence->>'challenger_graded_n')::int >= 1250
                                                   ELSE false END
        END, false))
);
CREATE INDEX IF NOT EXISTS idx_governance_events_cohort ON model_governance_events (league, market, event_id);

CREATE OR REPLACE FUNCTION forbid_governance_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'model_governance_events are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION check_governance_event() RETURNS trigger AS $$
DECLARE
    last_state_id BIGINT;
    last_state_type TEXT;
    last_root_cause BIGINT;
BEGIN
    IF NEW.event_type = 'PROMOTED' THEN
        SELECT event_id, event_type INTO last_state_id, last_state_type
        FROM model_governance_events
        WHERE league = NEW.league AND market = NEW.market
          AND event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED', 'RELEGATED', 'SUSPENDED')
        ORDER BY event_id DESC LIMIT 1;
        IF last_state_type IN ('RELEGATED', 'SUSPENDED') THEN
            SELECT max(event_id) INTO last_root_cause FROM model_governance_events
            WHERE league = NEW.league AND market = NEW.market AND event_type = 'ROOT_CAUSE_APPROVED';
            IF last_root_cause IS NULL OR last_root_cause < last_state_id THEN
                RAISE EXCEPTION 'promotion after a failure needs an approved root cause recorded after the failure';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_governance_events_no_update
    BEFORE UPDATE OR DELETE ON model_governance_events
    FOR EACH ROW EXECUTE FUNCTION forbid_governance_mutation();
CREATE TRIGGER trg_governance_events_rules
    BEFORE INSERT ON model_governance_events
    FOR EACH ROW EXECUTE FUNCTION check_governance_event();

-- Current state per cohort, derived from the log: ACTIVE with a champion, or SUSPENDED with none.
CREATE OR REPLACE VIEW v_cohort_state AS
SELECT DISTINCT ON (league, market)
       league, market, event_id, event_type, occurred_at, approved_by,
       CASE WHEN event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED') THEN 'ACTIVE' ELSE 'SUSPENDED' END AS state,
       CASE WHEN event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED') THEN model_version_id END AS champion_model_version_id,
       CASE WHEN event_type = 'PROMOTED' THEN rollback_model_version_id END AS rollback_model_version_id
FROM model_governance_events
WHERE event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED', 'RELEGATED', 'SUSPENDED')
ORDER BY league, market, event_id DESC;

-- Registered challengers that are neither retired nor since promoted. They run in isolation: never published.
CREATE OR REPLACE VIEW v_cohort_shadows AS
SELECT r.league, r.market, r.model_version_id
FROM model_governance_events r
WHERE r.event_type = 'CHALLENGER_REGISTERED'
  AND NOT EXISTS (
      SELECT 1 FROM model_governance_events x
      WHERE x.league = r.league AND x.market = r.market AND x.model_version_id = r.model_version_id
        AND x.event_type IN ('CHALLENGER_RETIRED', 'PROMOTED') AND x.event_id > r.event_id);

-- ---------- Season report views ----------

-- Dedupes by natural key (earliest prediction_id per match/market/side/
-- line/subject wins) before anything gets aggregated, so a fixture that
-- somehow got slated twice can't double-count in the views below without
-- touching the ledger itself -- every row still exists in `predictions`
-- exactly as inserted. See sql/migrations/0003_dedupe_scorecard_views.sql.
--
-- ADR-010 exception, deliberate: a "final pass" close-to-kickoff refresh
-- for PLAYER_GOALS/PLAYER_SAVES (scripts/generate_slate.py's
-- generate_final_pass_for_fixture()) intentionally writes a SECOND row
-- under the same natural key, using the real confirmed lineup instead
-- of the early absence-rate prior -- a genuinely more-informed
-- prediction, not a duplicate-slate bug. That row's model_versions.
-- model_name is always 'player_props_lineup_confirmed_v1'; it wins the
-- tie-break over an earlier prediction_id (the original "earliest wins"
-- rule stays the fallback, so it still protects against the real
-- duplicate-slate incident ADR-010 references -- two rows under the
-- SAME model_name still resolve to the earliest one).
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
               ORDER BY (mv.model_name = 'player_props_lineup_confirmed_v1') DESC,
                        p.prediction_id
           ) AS rn
    FROM predictions p
    JOIN model_versions mv ON mv.model_version_id = p.model_version_id
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
-- section. Scheduled fixtures only (migration 0043): pre-game model
-- estimate vs pre-game market estimate, skipping void-graded predictions.
-- Graded matches live in v_graded_predictions / v_closing_line_value.
-- See sql/migrations/0011_market_comparison_view.sql and 0043.
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
    LEFT JOIN prediction_grades g ON g.prediction_id = p.prediction_id
    WHERE p.market = '1X2'
      AND (g.outcome IS NULL OR g.outcome <> 'void')
) p
JOIN matches m ON m.match_id = p.match_id
JOIN teams th ON th.team_id = m.home_team_id
JOIN teams ta ON ta.team_id = m.away_team_id
JOIN seasons s ON s.season_id = m.season_id
JOIN leagues l ON l.league_id = s.league_id
JOIN match_odds mo ON mo.match_id = m.match_id AND LOWER(mo.selection) = p.side
WHERE p.rn = 1
  AND m.status = 'scheduled'
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

-- Every competitive fixture a tracked team played, in any competition
-- (league, domestic cups, continental), for rest/congestion features.
-- Separate from `matches` on purpose: cup and continental games must
-- never enter training or grading. See sql/migrations/0042_team_fixtures.sql.
CREATE TABLE IF NOT EXISTS team_fixtures (
    team_id        INT NOT NULL REFERENCES teams(team_id),
    api_fixture_id BIGINT NOT NULL,
    kickoff_utc    TIMESTAMPTZ NOT NULL,
    competition    TEXT NOT NULL,
    api_league_id  INT NOT NULL,
    is_home        BOOLEAN NOT NULL,
    status_short   TEXT,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, api_fixture_id)
);

CREATE INDEX IF NOT EXISTS idx_team_fixtures_team_kickoff
    ON team_fixtures (team_id, kickoff_utc);

-- Closing-line value on 1X2 (migration 0026): our probability vs the average closing market probability.
CREATE OR REPLACE VIEW v_closing_line_value AS
SELECT p.prediction_id,
       p.match_id,
       p.statement,
       p.side,
       p.probability AS our_probability,
       avg(m.closing_probability) AS avg_closing_market_probability,
       (p.probability - avg(m.closing_probability)) AS edge_vs_closing,
       g.outcome,
       g.actual_value
FROM predictions p
JOIN prediction_grades g ON g.prediction_id = p.prediction_id
JOIN v_odds_movement m ON m.match_id = p.match_id AND m.market = p.market AND lower(m.selection) = p.side
WHERE p.market = '1X2'
GROUP BY p.prediction_id, p.match_id, p.statement, p.side, p.probability, g.outcome, g.actual_value;

-- FBref vs API-Football corners / shots on target, per team-match (migrations 0025, 0040).
CREATE OR REPLACE VIEW v_source_reconciliation AS
SELECT fb.match_id,
       fb.team_id,
       fb.corners AS corners_fbref,
       af.corners AS corners_api_football,
       (fb.corners - af.corners) AS corners_diff,
       fb.shots_on_target AS sot_fbref,
       af.shots_on_target AS sot_api_football,
       (fb.shots_on_target - af.shots_on_target) AS sot_diff
FROM team_match_stats_by_source fb
JOIN team_match_stats_by_source af
  ON af.match_id = fb.match_id AND af.team_id = fb.team_id AND af.source = 'api_football'
WHERE fb.source = 'fbref' AND fb.corners IS NOT NULL AND af.corners IS NOT NULL;
