-- Adds player_injuries (Todoist: "futbol-modelo: lineup/injury news as
-- a model feature", Phase 2). Live-verified 2026-09-27: API-Football's
-- /injuries endpoint works for both upcoming and already-played
-- fixtures, keyed by fixture id -- no bulk-by-season equivalent, one
-- call per fixture (see scripts/backfill_injuries.py).
--
-- Follows match_odds' shape (sql/schema.sql), not the settled-stat
-- shape (player_match_stats): this is a live, re-fetched snapshot that
-- can change right up until kickoff, not a historical fact fixed once
-- a match finishes. fetched_at tracks how fresh the last poll was --
-- see generate_slate.py's fit_player_goals_model()/fit_player_saves_model()
-- for how a stale-or-missing row here falls back to a training-set-wide
-- absence-rate prior (player_injury_features, sql/features.sql) instead
-- of blocking.
CREATE TABLE IF NOT EXISTS player_injuries (
    match_id    INT NOT NULL REFERENCES matches(match_id),
    player_id   INT NOT NULL REFERENCES players(player_id),
    status      TEXT NOT NULL CHECK (status IN ('out', 'questionable')),
    reason      TEXT,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, player_id)
);

-- Widen predictions_market_check the same way migration 0034 did for
-- CARDS -- PLAYER_GOALS/PLAYER_SAVES are already in the CHECK list, so
-- this migration doesn't need to touch it; kept as a comment here
-- rather than a no-op ALTER so the next person reading this file in
-- order doesn't wonder why it's missing.
