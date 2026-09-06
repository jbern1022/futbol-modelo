-- NBA vertical slice, step 2: player points props -- the second (and
-- last, per the scope-guard ticket) NBA market. Needs three things
-- nothing existing provides: a PLAYER_POINTS market value, a stable
-- per-source player id column (same pattern as players.api_football_id
-- etc.), and somewhere to store per-game player box scores for this
-- sport (player_match_stats' columns are soccer-shaped -- goals,
-- assists, xg -- not points/minutes).

ALTER TABLE futbol.players ADD COLUMN IF NOT EXISTS nba_player_id BIGINT UNIQUE;

ALTER TABLE futbol.predictions DROP CONSTRAINT predictions_market_check;
ALTER TABLE futbol.predictions ADD CONSTRAINT predictions_market_check CHECK (market IN (
    -- soccer (live)
    '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT',
    'PLAYER_GOALS', 'PLAYER_SAVES',
    -- NFL (live)
    'MONEYLINE', 'SPREAD', 'TOTAL_POINTS',
    -- NBA (live)
    'PLAYER_POINTS'
));

CREATE TABLE IF NOT EXISTS futbol.player_match_stats_nba (
    match_id   INT NOT NULL REFERENCES futbol.matches(match_id),
    player_id  INT NOT NULL REFERENCES futbol.players(player_id),
    team_id    INT NOT NULL REFERENCES futbol.teams(team_id),
    minutes    NUMERIC(5,1),
    points     INT,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_player_match_stats_nba_player
    ON futbol.player_match_stats_nba (player_id);
