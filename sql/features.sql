-- =============================================================
-- Phase D: feature materialization (rolling as-of, leakage-safe)
-- Re-runnable. Run after every ingestion batch.
--
--   psql "$FUTBOL_DSN" -f sql/features.sql
--
-- Builds into temporary names and swaps them in inside a single transaction.
-- The previous version did DROP TABLE followed by CREATE TABLE outside any
-- transaction, so for the duration of the rebuild the feature tables did not
-- exist at all — any concurrent slate generation or model training would fail
-- with "relation team_match_features does not exist". Readers now see either
-- the old tables or the new ones, never a gap.
--
-- Note the rebuild is still a full recompute rather than incremental. That is
-- fine at current volumes and keeps the window-function definitions honest;
-- revisit if it stops finishing quickly.
-- =============================================================
BEGIN;

SET search_path TO futbol;
SET LOCAL lock_timeout = '30s';

DROP TABLE IF EXISTS team_match_features_new;
CREATE TABLE team_match_features_new AS
WITH base AS (
    SELECT
        s.match_id, s.team_id, s.is_home,
        m.kickoff_utc, m.season_id,
        se.league_id,
        s.corners, s.shots, s.shots_on_target, s.xg,
        s.possession_pct, s.ppda, s.deep_completions,
        s.fouls, s.yellows, s.reds,
        o.corners  AS corners_conceded,
        o.shots    AS shots_conceded,
        o.shots_on_target AS sot_conceded,
        o.xg       AS xg_conceded
    FROM team_match_stats s
    JOIN matches m USING (match_id)
    JOIN seasons se ON se.season_id = m.season_id
    JOIN team_match_stats o
      ON o.match_id = s.match_id AND o.team_id <> s.team_id
    WHERE m.status = 'final'
),
rolled AS (
    SELECT
        match_id, team_id, is_home, kickoff_utc, season_id, league_id,
        AVG(corners)          OVER w5  AS corners_for_r5,
        AVG(corners)          OVER w10 AS corners_for_r10,
        AVG(corners_conceded) OVER w5  AS corners_against_r5,
        AVG(corners_conceded) OVER w10 AS corners_against_r10,
        AVG(shots)            OVER w5  AS shots_for_r5,
        AVG(shots)            OVER w10 AS shots_for_r10,
        AVG(shots_conceded)   OVER w5  AS shots_against_r5,
        AVG(shots_conceded)   OVER w10 AS shots_against_r10,
        AVG(shots_on_target)  OVER w5  AS sot_for_r5,
        AVG(shots_on_target)  OVER w10 AS sot_for_r10,
        AVG(sot_conceded)     OVER w5  AS sot_against_r5,
        AVG(sot_conceded)     OVER w10 AS sot_against_r10,
        AVG(fouls)             OVER w5  AS fouls_for_r5,
        AVG(yellows)           OVER w5  AS yellows_for_r5,
        AVG(yellows)           OVER w10 AS yellows_for_r10,
        AVG(reds)               OVER w5  AS reds_for_r5,
        AVG(xg)               OVER w5  AS xg_for_r5,
        AVG(xg_conceded)      OVER w5  AS xg_against_r5,
        AVG(possession_pct)   OVER w5  AS possession_r5,
        AVG(ppda)             OVER w5  AS ppda_r5,
        AVG(deep_completions) OVER w5  AS deep_completions_r5,
        LAG(kickoff_utc)      OVER seq AS prev_kickoff,
        COUNT(*)              OVER w10 AS n_prior
    FROM base
    WINDOW
        seq AS (PARTITION BY team_id ORDER BY kickoff_utc),
        w5  AS (PARTITION BY team_id ORDER BY kickoff_utc
                ROWS BETWEEN 5  PRECEDING AND 1 PRECEDING),
        w10 AS (PARTITION BY team_id ORDER BY kickoff_utc
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING)
)
SELECT r.*,
       EXTRACT(EPOCH FROM (r.kickoff_utc - r.prev_kickoff))/86400.0 AS rest_days
FROM rolled r;

CREATE INDEX idx_tmf_new ON team_match_features_new (match_id, team_id);

DROP TABLE IF EXISTS player_match_features_new;
CREATE TABLE player_match_features_new AS
SELECT
    p.match_id, p.player_id, p.team_id,
    m.kickoff_utc,
    AVG(p.shots)   OVER w5  AS p_shots_r5,
    AVG(p.shots)   OVER w10 AS p_shots_r10,
    AVG(p.minutes) OVER w5  AS p_minutes_r5,
    AVG(p.xg)      OVER w5  AS p_xg_r5,
    AVG(p.goals)   OVER w10 AS p_goals_r10,
    AVG(p.key_passes) OVER w5 AS p_key_passes_r5,
    AVG(p.saves)   OVER w5  AS p_saves_r5,
    COUNT(*)       OVER w10 AS n_prior
FROM player_match_stats p
JOIN matches m USING (match_id)
WHERE m.status = 'final'
WINDOW
    w5  AS (PARTITION BY p.player_id ORDER BY m.kickoff_utc
            ROWS BETWEEN 5  PRECEDING AND 1 PRECEDING),
    w10 AS (PARTITION BY p.player_id ORDER BY m.kickoff_utc
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING);

CREATE INDEX idx_pmf_new ON player_match_features_new (match_id, player_id);

-- Atomic swap. Everything above built under _new names; these renames are the
-- only moment readers are affected, and they are over instantly.
DROP TABLE IF EXISTS team_match_features;
ALTER TABLE team_match_features_new RENAME TO team_match_features;
ALTER INDEX idx_tmf_new RENAME TO idx_tmf;

DROP TABLE IF EXISTS player_match_features;
ALTER TABLE player_match_features_new RENAME TO player_match_features;
ALTER INDEX idx_pmf_new RENAME TO idx_pmf;

-- Refuse to commit an empty rebuild. A source outage or a botched ingest that
-- leaves zero rows should abort here, keeping the previous tables, rather than
-- silently replacing good features with nothing and letting the next training
-- run fail its baseline gate for reasons nobody can trace.
DO $$
DECLARE
    n_team INT;
    n_player INT;
BEGIN
    SELECT COUNT(*) INTO n_team   FROM team_match_features;
    SELECT COUNT(*) INTO n_player FROM player_match_features;
    IF n_team = 0 THEN
        RAISE EXCEPTION 'refusing to commit: team_match_features rebuilt to 0 rows';
    END IF;
    RAISE NOTICE 'team_match_features: % rows, player_match_features: % rows',
                 n_team, n_player;
END $$;

COMMIT;
