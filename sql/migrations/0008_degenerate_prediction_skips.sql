-- Closes a product question raised twice (see Todoist): build_slate()
-- silently drops any candidate whose probability rounds to exactly 0
-- or 1 (a newly-promoted team with almost no fitted history can
-- produce this) -- a real, necessary guard against a
-- predictions.probability CHECK-constraint violation that would
-- otherwise take the whole batch down, but one with zero visibility.
-- Other markets for the same fixture go through fine; only the
-- degenerate candidate vanished with no trace anywhere. This table
-- makes those drops queryable instead of invisible.

CREATE TABLE IF NOT EXISTS degenerate_prediction_skips (
    skip_id            BIGSERIAL PRIMARY KEY,
    match_id           INT NOT NULL REFERENCES matches(match_id),
    market             TEXT NOT NULL,
    statement          TEXT NOT NULL,
    side               TEXT,
    line               NUMERIC(6,2),
    subject_team_id    INT REFERENCES teams(team_id),
    subject_player_id  INT REFERENCES players(player_id),
    raw_probability    DOUBLE PRECISION NOT NULL,
    detected_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_degenerate_skips_match ON degenerate_prediction_skips(match_id);
