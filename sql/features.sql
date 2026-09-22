-- =============================================================
-- Phase D: feature materialization (rolling as-of, leakage-safe)
-- Re-runnable: drops and rebuilds. Run after every ingestion batch.
-- =============================================================
SET search_path TO futbol;

DROP TABLE IF EXISTS team_match_features;
CREATE TABLE team_match_features AS
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

CREATE INDEX idx_tmf ON team_match_features (match_id, team_id);

-- Referee tendency (Todoist: "futbol-modelo: referee-tendencies feature
-- for CARDS market" -- CARDS is the one market that fails baseline
-- outright; matches.referee, added in migration 0033, was previously
-- ingested and silently discarded). Kept as its own small table rather
-- than added to team_match_features above: this is a per-MATCH
-- (referee) signal, not a per-team one -- both the home and away rows
-- of a match share the same referee_avg_cards_r10 -- and every other
-- market's query already reads team_match_features, so a new column
-- there would need to be threaded through markets that have no use for
-- it. Same leakage-safe as-of pattern as the rolling windows above:
-- only a referee's PRIOR officiated matches count, partitioned by
-- referee and ordered by kickoff.
DROP TABLE IF EXISTS referee_match_features;
CREATE TABLE referee_match_features AS
WITH match_cards AS (
    SELECT m.match_id, m.kickoff_utc, m.referee,
           SUM(s.yellows) AS total_yellows,
           SUM(s.fouls)   AS total_fouls
    FROM matches m
    JOIN team_match_stats s USING (match_id)
    WHERE m.status = 'final' AND m.referee IS NOT NULL
    GROUP BY m.match_id, m.kickoff_utc, m.referee
)
SELECT
    match_id, referee, kickoff_utc,
    AVG(total_yellows) OVER w10 AS referee_avg_cards_r10,
    AVG(total_fouls)   OVER w10 AS referee_avg_fouls_r10,
    COUNT(*)            OVER w10 AS referee_n_prior
FROM match_cards
WINDOW w10 AS (PARTITION BY referee ORDER BY kickoff_utc
               ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING);

CREATE INDEX idx_rmf ON referee_match_features (match_id);

DROP TABLE IF EXISTS player_match_features;
CREATE TABLE player_match_features AS
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

CREATE INDEX idx_pmf ON player_match_features (match_id, player_id);
