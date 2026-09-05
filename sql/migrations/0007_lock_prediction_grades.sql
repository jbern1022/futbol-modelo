-- Closes a gap flagged in CLAIMS.md: `predictions` already has a
-- trigger rejecting UPDATE/DELETE (forbid_prediction_mutation), but
-- `prediction_grades` only relied on its PRIMARY KEY (prediction_id)
-- to stop a second INSERT for the same prediction -- nothing stopped
-- a raw UPDATE from silently rewriting an existing grade's outcome.
-- Every real writer (src/grading/grader.py, scripts/auto_grade.py,
-- sql/void_duplicate_match_predictions.sql) only ever INSERTs, so this
-- trigger matches how the table is already used in practice and
-- changes no real behavior.

CREATE OR REPLACE FUNCTION forbid_grade_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'prediction_grades are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prediction_grades_no_update ON prediction_grades;
CREATE TRIGGER trg_prediction_grades_no_update
    BEFORE UPDATE OR DELETE ON prediction_grades
    FOR EACH ROW EXECUTE FUNCTION forbid_grade_mutation();
