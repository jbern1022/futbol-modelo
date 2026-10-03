-- Per-source xG (2026-10-03). API-Football's /fixtures/statistics
-- reports expected_goals; it now fills team_match_stats.xg for seasons
-- Understat doesn't cover (rescaled to Understat's scale, see
-- src/ingestion/api_football.py store_api_football_xg). The raw,
-- unscaled API-Football value is kept here so the two providers stay
-- comparable in v_source_reconciliation-style checks.
ALTER TABLE futbol.team_match_stats_by_source ADD COLUMN IF NOT EXISTS xg NUMERIC(6,3);
