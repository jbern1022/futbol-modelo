-- Expands odds ingestion beyond 1X2 to also cover BTTS (team-level, no
-- new column needed) and Anytime Goal Scorer (player-level -- needs a
-- player identity column match_odds/match_odds_history never had).
--
-- Nullable, not resolved by api_football_id the way every other player
-- reference in this schema is (see resolve_or_create_player_id's
-- comment: "no name-based conflict resolution... the numeric id is the
-- only safe key"). The odds provider only gives a bare player NAME
-- string, no id -- src/ingestion/api_football.py resolves it by
-- matching against the specific match's two known rosters (not a
-- global name search) and leaves player_id NULL rather than guess on
-- anything ambiguous. Nullable FK reflects that this is a best-effort
-- link, not a guaranteed one.
ALTER TABLE match_odds ADD COLUMN IF NOT EXISTS player_id INT REFERENCES players(player_id);
ALTER TABLE match_odds_history ADD COLUMN IF NOT EXISTS player_id INT REFERENCES players(player_id);

CREATE INDEX IF NOT EXISTS idx_match_odds_player ON match_odds(player_id) WHERE player_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_odds_history_player ON match_odds_history(player_id) WHERE player_id IS NOT NULL;

-- v_odds_movement (migration 0019) is the deliberate read boundary for
-- match_odds_history -- futbol_ro has no direct grant on the table
-- itself (see migration 0028's comment). Recreate it to also surface
-- player_id so a future join (e.g. a player-props bankroll sim) has it
-- without a further migration.
-- player_id appended at the end, not inserted where it logically
-- belongs (next to selection) -- CREATE OR REPLACE VIEW can only add
-- trailing columns, not reorder/insert existing ones, without a DROP
-- (which would also drop the futbol_ro grant from migration 0020).
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
