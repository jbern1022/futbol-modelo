-- Historical odds archive (opening -> closing line), first half: the
-- append-only table. match_odds itself is UNIQUE (match_id,
-- bookmaker_id, market, selection) and upserts on every fetch --
-- correct for "current odds" display, but it means every earlier
-- snapshot is destroyed the moment a newer one lands, so no movement
-- analysis is possible from it alone (see src/ingestion/api_football.py's
-- fetch_and_store_odds() docstring, which already says this out loud).
--
-- match_odds_history is the same shape, no UNIQUE constraint -- every
-- fetch appends a new row instead of overwriting. Opening/closing line
-- for a given (match, bookmaker, market, selection) is then just
-- MIN/MAX(fetched_at) over the matching rows, no separate bookkeeping
-- needed.
CREATE TABLE IF NOT EXISTS match_odds_history (
    odds_history_id      BIGSERIAL PRIMARY KEY,
    match_id             INT NOT NULL REFERENCES matches(match_id),
    bookmaker_id          INT,
    bookmaker_name        TEXT,
    market                TEXT NOT NULL,
    selection             TEXT NOT NULL,
    decimal_odds          NUMERIC(8,3) NOT NULL,
    implied_probability   NUMERIC(6,5),
    no_vig_probability    NUMERIC(6,5),
    fetched_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_match_odds_history_match
    ON match_odds_history(match_id, bookmaker_id, market, selection, fetched_at);

-- Opening vs closing line per (match, bookmaker, market, selection) --
-- "our predictions beat the closing line" needs both ends, not just
-- the latest snapshot. If only one snapshot exists so far, opening and
-- closing are the same row -- no movement observed yet, not an error.
CREATE OR REPLACE VIEW v_odds_movement AS
SELECT
    o.match_id, o.bookmaker_id, o.bookmaker_name, o.market, o.selection,
    o.decimal_odds AS opening_odds, o.no_vig_probability AS opening_probability,
    o.fetched_at AS opening_fetched_at,
    c.decimal_odds AS closing_odds, c.no_vig_probability AS closing_probability,
    c.fetched_at AS closing_fetched_at
FROM (
    SELECT DISTINCT ON (match_id, bookmaker_id, market, selection)
        match_id, bookmaker_id, bookmaker_name, market, selection,
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
