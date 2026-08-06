-- =============================================================
-- Migration 004 — publish what was voided and why.
--
--   psql "$FUTBOL_DSN" -f sql/migrations/004_void_summary_view.sql
--
-- v_season_scorecard and v_calibration both filter `outcome <> 'void'`, which
-- is correct — a void is not a miss and must not drag a hit rate down. But it
-- means voided predictions vanish from every published figure with nothing to
-- say they existed.
--
-- That is fine when voiding is rare and mechanical, and dangerous when it is
-- neither: it is the one operation that can remove an inconvenient prediction
-- from the record. Publishing the counts alongside the rates is what keeps it
-- honest — a table that says "82 voided, 50 because the player did not
-- feature" is more trustworthy than a clean one, not less.
--
-- Safe to re-run.
-- =============================================================

BEGIN;

CREATE OR REPLACE VIEW futbol.v_void_summary AS
SELECT
    l.code                                AS league,
    s.label                               AS season,
    p.market,
    COALESCE(g.void_reason, 'unspecified') AS void_reason,
    COUNT(*)                              AS n,
    MIN(m.kickoff_utc)                    AS earliest,
    MAX(m.kickoff_utc)                    AS latest
FROM futbol.predictions p
JOIN futbol.prediction_grades g USING (prediction_id)
JOIN futbol.matches m USING (match_id)
JOIN futbol.seasons s USING (season_id)
JOIN futbol.leagues l USING (league_id)
WHERE g.outcome = 'void'
GROUP BY l.code, s.label, p.market, COALESCE(g.void_reason, 'unspecified');

COMMIT;
