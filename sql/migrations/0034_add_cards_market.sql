-- Adds CARDS to the market CHECK constraint (Todoist: "futbol-modelo:
-- referee-tendencies feature for CARDS market" -- wiring CARDS into
-- the live slate generator once the referee-tendency feature flipped
-- it past baseline). Found live 2026-09-22 while wiring generate_slate.py:
-- CARDS was never actually addable before this -- the constraint would
-- have rejected the very first CARDS insert and likely broken the
-- whole futbol-auto-slate run. See scripts/generate_slate.py's
-- PROPS_MARKETS["CARDS"] for the model itself.
ALTER TABLE futbol.predictions DROP CONSTRAINT predictions_market_check;
ALTER TABLE futbol.predictions ADD CONSTRAINT predictions_market_check CHECK (market IN (
    -- soccer (live)
    '1X2', 'BTTS', 'TOTAL_GOALS', 'CORNERS', 'SOT', 'CARDS',
    'PLAYER_GOALS', 'PLAYER_SAVES',
    -- NFL (live)
    'MONEYLINE', 'SPREAD', 'TOTAL_POINTS',
    'PLAYER_PASS_YARDS', 'PLAYER_RUSH_YARDS',
    'PLAYER_RECEIVING_YARDS', 'PLAYER_RECEPTIONS', 'PLAYER_ANYTIME_TD',
    -- NBA (live)
    'PLAYER_POINTS'
));
