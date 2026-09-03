-- Storage half of "real bookmaker odds comparison" (TOP RECOMMENDATION,
-- ranked #1 across sessions, per Todoist). One row per (match,
-- bookmaker, market, selection) -- ON CONFLICT keeps this the latest
-- known snapshot, not a full time series; a separate opening->closing
-- line archive is a deliberately deferred, later ticket on top of
-- this. The Track Record UI comparison itself is also deferred --
-- this migration and src/ingestion/api_football.py's
-- fetch_and_store_odds() are the ingestion/storage half only.

CREATE TABLE IF NOT EXISTS match_odds (
    odds_id             BIGSERIAL PRIMARY KEY,
    match_id            INT NOT NULL REFERENCES matches(match_id),
    bookmaker_id        INT,
    bookmaker_name      TEXT,
    market              TEXT NOT NULL,
    selection           TEXT NOT NULL,
    decimal_odds        NUMERIC(8,3) NOT NULL,
    implied_probability NUMERIC(6,5),
    no_vig_probability  NUMERIC(6,5),
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, bookmaker_id, market, selection)
);

CREATE INDEX IF NOT EXISTS idx_match_odds_match ON match_odds(match_id);
