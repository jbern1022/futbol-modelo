-- Every competitive fixture a tracked team played, in any competition
-- (league, domestic cups, continental), from API-Football's per-team
-- /fixtures. For rest/congestion features (Todoist 6hf57M7W6CgXjH77,
-- 6hf54j2hMP87xjR7). A separate table on purpose: cup and continental
-- games must never enter `matches`, which drives training and grading.
-- Friendlies are not stored (no competitive workload).
CREATE TABLE IF NOT EXISTS futbol.team_fixtures (
    team_id        INT NOT NULL REFERENCES futbol.teams(team_id),
    api_fixture_id BIGINT NOT NULL,
    kickoff_utc    TIMESTAMPTZ NOT NULL,
    competition    TEXT NOT NULL,
    api_league_id  INT NOT NULL,
    is_home        BOOLEAN NOT NULL,
    status_short   TEXT,
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, api_fixture_id)
);
CREATE INDEX IF NOT EXISTS idx_team_fixtures_team_kickoff ON futbol.team_fixtures (team_id, kickoff_utc);
