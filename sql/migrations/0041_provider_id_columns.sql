-- Separate per-provider match ids (Todoist 6hfxhQccV87r4jcx).
--
-- matches.external_ref is one TEXT column shared by every source
-- ('understat:<id>', 'api-football:<id>', 'nba:...', 'nflverse:...').
-- A match can carry only one, so historical EPL/SERIE_A/LA_LIGA rows
-- (created by Understat) could never get an API-Football fixture id, and
-- loading Understat data onto API-Football-created rows either dropped
-- the shots (exact kickoff match: the row keeps its api-football ref, and
-- shots attach by understat ref) or created a duplicate match (kickoff
-- differs). The 2025-26 La Liga Understat load made 4 such duplicates.
--
-- external_ref stays as it is (NFL/NBA/WC still use it, and every
-- existing writer keeps working). Two new columns hold the soccer
-- provider ids, a trigger keeps them filled whenever a writer sets
-- external_ref, and code that needs an API-Football id reads
-- api_football_fixture_id.

ALTER TABLE futbol.matches
    ADD COLUMN IF NOT EXISTS api_football_fixture_id BIGINT,
    ADD COLUMN IF NOT EXISTS understat_game_id TEXT;

-- 1) The four La Liga 2025-26 duplicate pairs. Keeper = the Understat row
--    (older, has the shots); orphan = the API-Football row created later
--    with a different kickoff. Same treatment as ADR-005: nothing deleted,
--    the orphan's ref gets a superseded marker, and status 'duplicate'
--    takes it out of every status='final' query (training, grading,
--    features). Guard: none of the orphans may carry a prediction.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM futbol.predictions
               WHERE match_id IN (63093, 63094, 63152, 62852)) THEN
        RAISE EXCEPTION 'duplicate-match orphan has predictions -- resolve by hand (ADR-005)';
    END IF;
END $$;

UPDATE futbol.matches o
SET status = 'duplicate',
    external_ref = o.external_ref || '-superseded-by-' || v.keeper
FROM (VALUES (63093, 14685), (63094, 14687), (63152, 14737), (62852, 14444)) AS v(orphan, keeper)
WHERE o.match_id = v.orphan AND o.external_ref NOT LIKE '%superseded%';

-- 2) Fill the new columns from external_ref.
UPDATE futbol.matches
SET api_football_fixture_id = substring(external_ref FROM '^api-football:(\d+)$')::bigint
WHERE external_ref ~ '^api-football:\d+$' AND api_football_fixture_id IS NULL;

UPDATE futbol.matches
SET understat_game_id = substring(external_ref FROM '^understat:(.+)$')
WHERE external_ref ~ '^understat:.+' AND understat_game_id IS NULL;

-- 3) The keepers take over their orphan's API-Football fixture id.
UPDATE futbol.matches k
SET api_football_fixture_id = v.fixture_id
FROM (VALUES (14685, 1391139), (14687, 1391144), (14737, 1391181), (14444, 1390887))
     AS v(keeper, fixture_id)
WHERE k.match_id = v.keeper AND k.api_football_fixture_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS matches_api_football_fixture_id
    ON futbol.matches (api_football_fixture_id) WHERE api_football_fixture_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS matches_understat_game_id
    ON futbol.matches (understat_game_id) WHERE understat_game_id IS NOT NULL;

-- 4) Keep the columns in step with every existing external_ref writer.
--    Only exact '<provider>:<id>' values count, so a '-superseded-by-N'
--    rename never moves an id.
CREATE OR REPLACE FUNCTION futbol.sync_provider_ids() RETURNS trigger AS $$
BEGIN
    IF NEW.external_ref ~ '^api-football:\d+$' AND NEW.api_football_fixture_id IS NULL THEN
        NEW.api_football_fixture_id := substring(NEW.external_ref FROM '^api-football:(\d+)$')::bigint;
    ELSIF NEW.external_ref ~ '^understat:.+' AND NEW.understat_game_id IS NULL THEN
        NEW.understat_game_id := substring(NEW.external_ref FROM '^understat:(.+)$');
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_provider_ids ON futbol.matches;
CREATE TRIGGER trg_sync_provider_ids
    BEFORE INSERT OR UPDATE OF external_ref ON futbol.matches
    FOR EACH ROW EXECUTE FUNCTION futbol.sync_provider_ids();
