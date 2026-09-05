-- One-off cleanup for the duplicate-match bug (see Todoist). 9 real
-- api-football fixtures each ended up as two match rows (same
-- external_ref, different match_id) because a kickoff-time correction
-- between ingestion runs didn't match upsert_match's old conflict key
-- (season_id, home_team_id, away_team_id, kickoff_utc) -- kickoff_utc
-- was part of the identity, so a corrected time inserted a new row
-- instead of updating the existing one.
--
-- Keeper vs orphan per pair: whichever side reached status='final' wins
-- outright (it has real results); for still-scheduled pairs, the HIGHER
-- match_id wins -- verified consistent with the match_id numbering
-- across all 3 already-resolved pairs (the 'final' side was always the
-- higher id, i.e. the more recently (re-)ingested, more current row).
--
-- This does NOT delete or merge match rows -- predictions and
-- prediction_grades are immutable, so existing predictions must keep
-- pointing at the match_id they were actually written against. Instead:
--   1. Void every orphan-side prediction that has no grade yet, with an
--      explicit reason (append-only, doesn't violate immutability).
--   2. Free up the orphan's external_ref (append '-superseded-by-N'
--      rather than nulling it, so the audit trail survives) so a future
--      UNIQUE constraint on external_ref can be added.
--
--     psql "$FUTBOL_DSN" -f sql/void_duplicate_match_predictions.sql

BEGIN;

INSERT INTO futbol.prediction_grades (prediction_id, outcome, actual_value, graded_at, grader_version)
SELECT p.prediction_id, 'void', NULL, now(), 'grader-1.0-duplicate-match-cleanup'
FROM futbol.predictions p
LEFT JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
WHERE p.match_id IN (4420, 4434, 4441, 4469, 4482, 4483, 4485)
  AND g.prediction_id IS NULL;

UPDATE futbol.matches
SET external_ref = external_ref || '-superseded-by-' || keeper
FROM (VALUES
    (4420, 21250),
    (4434, 28301),
    (4441, 28307),
    (4469, 37225),
    (4482, 21125),
    (4483, 13285),
    (4485, 13288),
    (4573, 13375),
    (4682, 37441)
) AS pairs(orphan, keeper)
WHERE matches.match_id = pairs.orphan;

COMMIT;
