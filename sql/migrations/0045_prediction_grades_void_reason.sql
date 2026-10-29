-- Record prediction_grades.void_reason (found 2026-10-29 while diffing production against sql/schema.sql).
--
-- The column and its CHECK constraint exist in production and are used by api/main.py and
-- scripts/void_mls_sot.py, but no migration or schema file in git ever defined them, so a database
-- rebuilt from the repo lacked them and the API would fail. They were evidently added by hand.
-- This migration is a no-op on production (IF NOT EXISTS / existence-guarded) and makes a fresh
-- database match it. A void grade is still immutable (trigger from 0007); the reason is written with
-- the grade, never updated.
ALTER TABLE futbol.prediction_grades ADD COLUMN IF NOT EXISTS void_reason TEXT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'futbol.prediction_grades'::regclass
                     AND conname = 'prediction_grades_void_reason_only_when_void') THEN
        ALTER TABLE futbol.prediction_grades
            ADD CONSTRAINT prediction_grades_void_reason_only_when_void
            CHECK (void_reason IS NULL OR outcome = 'void');
    END IF;
END $$;
