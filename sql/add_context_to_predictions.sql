-- One-off migration for the already-running database (fresh installs get
-- this via schema.sql). Purely additive -- ALTER TABLE ADD COLUMN, no
-- existing rows touched, no conflict with the immutability trigger (that
-- blocks row UPDATE/DELETE, not schema changes).
--
-- Backing store for a "why" panel: the last-5 rolling stats / rest days
-- current_form() already computes at slate-generation time, previously
-- discarded after being fed into the model. Nullable -- only props
-- markets (CORNERS/SOT/PLAYER_GOALS/PLAYER_SAVES) populate this; 1X2/
-- BTTS/TOTAL_GOALS come from Dixon-Coles team ratings, a different kind
-- of "why" not covered here. Existing rows stay NULL permanently --
-- same "old rows can't be retrofitted" situation as the corners/SOT
-- team-label statement text earlier this session.
--
--     psql "$FUTBOL_DSN" -f sql/add_context_to_predictions.sql

ALTER TABLE futbol.predictions ADD COLUMN IF NOT EXISTS context JSONB;
