-- =============================================================
-- Migration 003 — record WHY a prediction was voided.
--
--   psql "$FUTBOL_DSN" -f sql/migrations/003_prediction_grades_void_reason.sql
--
-- Predictions that can never be graded previously sat ungraded forever,
-- retried nightly, counted as predictions made but absent from every hit-rate
-- figure. That quietly selects the published record on the basis of which
-- stats happened to arrive.
--
-- auto_grade now voids them under explicit rules, and a void is only
-- defensible if the reason is recorded and publishable. Encoding it into
-- grader_version would work without a migration but would make the reason
-- something you have to parse out of a version string, which is the wrong
-- answer for a project whose entire claim is auditability.
--
-- Reasons currently written:
--   player_absent      the player has no stats row for a match where other
--                      players do — they did not feature. Definitive on day
--                      one, so these void immediately.
--   stat_unavailable   the observed value never arrived. Voided only after a
--                      grace period, in case the source backfills it.
--   subject_missing    the prediction carries no subject id to look up. A data
--                      bug rather than a source gap; voided after the same
--                      grace period so it stays visible until then.
--
-- Safe to re-run.
-- =============================================================

BEGIN;

ALTER TABLE futbol.prediction_grades
    ADD COLUMN IF NOT EXISTS void_reason TEXT;

-- A reason is meaningless on a hit or a miss, and allowing one would let a
-- graded prediction carry void semantics.
ALTER TABLE futbol.prediction_grades
    DROP CONSTRAINT IF EXISTS prediction_grades_void_reason_only_when_void;
ALTER TABLE futbol.prediction_grades
    ADD CONSTRAINT prediction_grades_void_reason_only_when_void
    CHECK (void_reason IS NULL OR outcome = 'void');

COMMIT;
