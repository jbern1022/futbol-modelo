-- Expanded NFL prop platform: receiving yards, receptions (catches),
-- and anytime-TD, alongside the existing PLAYER_PASS_YARDS/
-- PLAYER_RUSH_YARDS. See src/models/nfl_player_props.py.
ALTER TABLE futbol.predictions DROP CONSTRAINT predictions_market_check;
ALTER TABLE futbol.predictions ADD CONSTRAINT predictions_market_check CHECK (market IN (
    -- soccer (live)
    '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT',
    'PLAYER_GOALS', 'PLAYER_SAVES',
    -- NFL (live)
    'MONEYLINE', 'SPREAD', 'TOTAL_POINTS',
    'PLAYER_PASS_YARDS', 'PLAYER_RUSH_YARDS',
    'PLAYER_RECEIVING_YARDS', 'PLAYER_RECEPTIONS', 'PLAYER_ANYTIME_TD',
    -- NBA (live)
    'PLAYER_POINTS'
));
