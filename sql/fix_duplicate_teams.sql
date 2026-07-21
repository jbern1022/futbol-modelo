-- One-time fix: merge duplicate team rows (root cause: teams.name
-- never had a UNIQUE constraint, so ON CONFLICT DO NOTHING in
-- upsert_team() was a no-op this entire project).
BEGIN;

SET search_path TO futbol;

CREATE TEMP TABLE team_canonical AS
SELECT name, MIN(team_id) AS keep_id
FROM teams
GROUP BY name;

CREATE TEMP TABLE team_dupes AS
SELECT t.team_id AS dup_id, c.keep_id
FROM teams t
JOIN team_canonical c ON c.name = t.name
WHERE t.team_id <> c.keep_id;

SELECT COUNT(*) AS duplicate_rows_to_remove FROM team_dupes;

UPDATE matches m SET home_team_id = d.keep_id
FROM team_dupes d WHERE m.home_team_id = d.dup_id;

UPDATE matches m SET away_team_id = d.keep_id
FROM team_dupes d WHERE m.away_team_id = d.dup_id;

UPDATE team_match_stats s SET team_id = d.keep_id
FROM team_dupes d WHERE s.team_id = d.dup_id;

UPDATE player_match_stats p SET team_id = d.keep_id
FROM team_dupes d WHERE p.team_id = d.dup_id;

UPDATE shots sh SET team_id = d.keep_id
FROM team_dupes d WHERE sh.team_id = d.dup_id;

UPDATE predictions pr SET subject_team_id = d.keep_id
FROM team_dupes d WHERE pr.subject_team_id = d.dup_id;

DELETE FROM teams t
USING team_dupes d
WHERE t.team_id = d.dup_id;

ALTER TABLE teams ADD CONSTRAINT teams_name_unique UNIQUE (name);

SELECT name, COUNT(*) FROM teams GROUP BY name HAVING COUNT(*) > 1;
-- ^ this should return ZERO rows.

COMMIT;
