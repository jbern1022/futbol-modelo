-- One-off migration for the already-running database (fresh installs
-- get this via schema.sql). Two new, empty tables -- purely additive,
-- nothing existing is touched.
--
-- Per-sport stat tables (2026-08-21 decision) rather than a shared core
-- + JSONB: full type safety and easy indexing per sport. matches/teams/
-- players/leagues/seasons stay shared; only the soccer-shaped stat
-- columns needed splitting. Column list is a best-effort standard NFL
-- box-score set (matches nflverse/nfl_data_py's shape) -- expect
-- adjustment once the actual NFL ingestion adapter is built.
--
--     psql "$FUTBOL_DSN" -f sql/add_nfl_stats_tables.sql

CREATE TABLE IF NOT EXISTS futbol.team_match_stats_nfl (
    match_id            INT NOT NULL REFERENCES futbol.matches(match_id),
    team_id             INT NOT NULL REFERENCES futbol.teams(team_id),
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

CREATE TABLE IF NOT EXISTS futbol.player_match_stats_nfl (
    match_id            INT NOT NULL REFERENCES futbol.matches(match_id),
    player_id           INT NOT NULL REFERENCES futbol.players(player_id),
    team_id             INT NOT NULL REFERENCES futbol.teams(team_id),
    position            TEXT,
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
    tackles             INT,
    sacks               NUMERIC(3,1),
    PRIMARY KEY (match_id, player_id)
);
