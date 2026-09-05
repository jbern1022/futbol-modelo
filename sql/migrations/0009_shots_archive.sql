-- Decides the shots table's retention lifecycle (open question, per
-- Todoist): event-level shot data grows fast and nobody had decided
-- what happens to old rows. Decision: keep the last 3 completed
-- seasons per league in the live `shots` table; archive anything
-- older into `shots_archive` (same shape, moved not deleted -- this
-- data feeds the planned custom xG model, so it stays queryable, just
-- out of the hot table). scripts/archive_old_shots.py does the actual
-- move, dry-run by default.

CREATE TABLE IF NOT EXISTS shots_archive (
    shot_id         BIGINT PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    player_id       INT REFERENCES players(player_id),
    team_id         INT REFERENCES teams(team_id),
    minute          INT,
    x               NUMERIC(6,4),
    y               NUMERIC(6,4),
    situation       TEXT,
    body_part       TEXT,
    result          TEXT,
    source_xg       NUMERIC(6,4),
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
