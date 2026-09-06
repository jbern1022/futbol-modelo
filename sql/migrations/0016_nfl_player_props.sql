-- NFL player props: QB passing yards, RB rushing yards -- the two
-- markets the ticket names as highest-volume/most liquid. Adds
-- PLAYER_PASS_YARDS/PLAYER_RUSH_YARDS, a stable per-source player id
-- column (same pattern as players.nba_player_id etc. -- nflverse's
-- gsis_id, e.g. '00-0034857', shared verbatim by import_weekly_data()
-- and import_depth_charts()), and a snap_pct column on the existing
-- (currently unpopulated) player_match_stats_nfl table -- the real
-- usage signal a rolling-yardage average alone can't see, since a
-- committee back's role can change week to week faster than a rolling
-- window catches up.

ALTER TABLE futbol.players ADD COLUMN IF NOT EXISTS nfl_player_id TEXT UNIQUE;
ALTER TABLE futbol.player_match_stats_nfl ADD COLUMN IF NOT EXISTS snap_pct NUMERIC(5,2);

ALTER TABLE futbol.predictions DROP CONSTRAINT predictions_market_check;
ALTER TABLE futbol.predictions ADD CONSTRAINT predictions_market_check CHECK (market IN (
    -- soccer (live)
    '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT',
    'PLAYER_GOALS', 'PLAYER_SAVES',
    -- NFL (live)
    'MONEYLINE', 'SPREAD', 'TOTAL_POINTS',
    'PLAYER_PASS_YARDS', 'PLAYER_RUSH_YARDS',
    -- NBA (live)
    'PLAYER_POINTS'
));
