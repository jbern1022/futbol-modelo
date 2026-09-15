-- Per-source raw stats, additive alongside the existing shared
-- team_match_stats table. team_match_stats has no source column, and
-- both src/ingestion/loader.py's FBref UPDATE and
-- src/ingestion/api_football.py's API-Football UPDATE write to the SAME
-- shared corners/shots_on_target/etc columns -- whichever source runs
-- last silently overwrites whatever the other one wrote, with no
-- historical record of what each source independently reported. This
-- table is what entities.record_source_stats() now writes to from all
-- 3 call sites (FBref, API-Football's live ingest, API-Football's
-- backfill), purely additive -- team_match_stats' existing behavior and
-- every downstream consumer of it (Dixon-Coles, props models) is
-- unchanged.
CREATE TABLE futbol.team_match_stats_by_source (
    match_id          INT NOT NULL REFERENCES futbol.matches(match_id),
    team_id           INT NOT NULL REFERENCES futbol.teams(team_id),
    source            TEXT NOT NULL,   -- 'fbref' | 'api_football'
    corners           INT,
    shots             INT,
    shots_on_target   INT,
    fouls             INT,
    yellows           INT,
    reds              INT,
    saves             INT,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, team_id, source)
);

GRANT SELECT ON futbol.team_match_stats_by_source TO futbol_ro;

-- Read-only reconciliation view: one row per (match_id, team_id) that
-- both sources have independently recorded a corners count for, with
-- the disagreement made explicit. NULL corners_diff rows are excluded
-- (WHERE both sides non-null) since there's nothing to reconcile until
-- both sources have actually reported.
CREATE VIEW futbol.v_source_reconciliation AS
SELECT
    fb.match_id, fb.team_id,
    fb.corners AS corners_fbref, af.corners AS corners_api_football,
    fb.corners - af.corners AS corners_diff,
    fb.shots_on_target AS sot_fbref, af.shots_on_target AS sot_api_football,
    fb.shots_on_target - af.shots_on_target AS sot_diff
FROM futbol.team_match_stats_by_source fb
JOIN futbol.team_match_stats_by_source af
  ON af.match_id = fb.match_id AND af.team_id = fb.team_id AND af.source = 'api_football'
WHERE fb.source = 'fbref'
  AND fb.corners IS NOT NULL AND af.corners IS NOT NULL;

GRANT SELECT ON futbol.v_source_reconciliation TO futbol_ro;
