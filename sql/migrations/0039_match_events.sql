-- Event-level data from API-Football's /fixtures/events -- the MLS
-- equivalent of Understat's shot-level `shots` table, which has zero
-- MLS coverage (Understat doesn't track MLS at all). Built to unblock
-- MLS in-play win-probability validation
-- (scripts/experiment_inplay_dixon_coles.py, ADR-011) and any future
-- MLS red-card calibration -- both currently EPL/SERIE_A-only because
-- they need real goal-minute (and, for red cards, card-minute) data,
-- which only `shots` provided before this.
--
-- Deliberately more general than "MLS goals only": same shape works
-- for any league's /fixtures/events response (Goal, Card, subst), so
-- a future red-card calibration backfill for another league can reuse
-- this table instead of re-fetching ad hoc the way
-- scripts/experiment_redcard_calibration.py currently does.
CREATE TABLE IF NOT EXISTS match_events (
    event_id        BIGSERIAL PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    team_id         INT REFERENCES teams(team_id),
    player_id       INT REFERENCES players(player_id),
    minute          INT NOT NULL,
    extra_minute    INT,                            -- stoppage-time offset, e.g. 90+8
    type            TEXT NOT NULL,                   -- Goal|Card|subst|Var
    detail          TEXT                             -- Normal Goal|Penalty|Yellow Card|Red Card|...
);

-- COALESCE every nullable column here -- team_id, player_id,
-- extra_minute, and detail can all be NULL, and Postgres never treats
-- two NULLs as equal in a unique index (the exact bug just found and
-- fixed for futbol.shots, migration 0037 -- not repeating it here).
CREATE UNIQUE INDEX IF NOT EXISTS match_events_natural_key ON match_events (
    match_id, COALESCE(team_id, -1), COALESCE(player_id, -1),
    minute, COALESCE(extra_minute, -1), type, COALESCE(detail, '')
);

CREATE INDEX IF NOT EXISTS idx_match_events_match ON match_events (match_id);
