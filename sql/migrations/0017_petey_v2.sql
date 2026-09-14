-- Petey v2: free-text -> validated JSON filter tree (docs/petey-spec.md,
-- ADR-003). Two pieces:
--
-- 1. v_petey_predictions -- the one fixed, safe base query the JSON
--    filter compiler is ever allowed to add a WHERE clause to. Built on
--    v_graded_predictions (already dedupes/excludes void grades) plus
--    the two things it's missing for this: team name (subject_team_id
--    is an id, not filterable text) and kickoff_date (not exposed at
--    all). Deliberately per-prediction, not pre-aggregated -- Petey
--    computes n/avg_confidence/hit_rate over whatever this filters
--    down to, the same never-show-Ollama-raw-rows pattern /v1/ask
--    already uses (ADR-002/003/008), just generalized to an arbitrary
--    filter instead of one fixed market+league lookup.
--
-- 2. petey_queries -- logs every free-text question alongside the JSON
--    filter Ollama proposed for it, per the spec's self-improving FAQ
--    loop (review real usage later, promote common patterns into new
--    preset buttons).

CREATE OR REPLACE VIEW v_petey_predictions AS
SELECT
    gp.prediction_id,
    gp.market,
    gp.league,
    gp.season,
    gp.side,
    gp.probability,
    gp.outcome,
    t.name AS team,
    m.kickoff_utc::date AS kickoff_date
FROM v_graded_predictions gp
JOIN matches m ON m.match_id = gp.match_id
LEFT JOIN teams t ON t.team_id = gp.subject_team_id;

CREATE TABLE IF NOT EXISTS petey_queries (
    query_id     SERIAL PRIMARY KEY,
    raw_text     TEXT NOT NULL,
    compiled_filter JSONB,          -- NULL if validation rejected Ollama's proposal
    rejected_reason TEXT,           -- set iff compiled_filter IS NULL
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
