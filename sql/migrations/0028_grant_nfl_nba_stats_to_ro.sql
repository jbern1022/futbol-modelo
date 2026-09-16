-- Found 2026-09-16 building /v1/player-stats: player_match_stats_nfl and
-- player_match_stats_nba (plus team_match_stats_nfl) were never granted
-- SELECT to futbol_ro -- both tables predate migration 0023's default-
-- privileges fix (created directly in schema.sql / migration 0015,
-- before that root-cause fix existed), so they fell through the same
-- gap 0023 closed for tables created afterward. No existing endpoint
-- read these tables directly before now (checked: only the new
-- /v1/player-stats code references them), so this wasn't yet a live
-- production bug -- just a real gap that would have silently 500'd
-- the new endpoint for NFL/NBA.
--
-- Left untouched on purpose: match_odds/match_odds_history (already
-- exposed indirectly via v_odds_movement, a deliberate view-only
-- boundary), petey_queries (SELECT deliberately withheld per migration
-- 0018 -- futbol_ro only has INSERT there), degenerate_prediction_skips,
-- shots_archive, team_venues, schema_migrations -- none read directly
-- by the API today; not grabbing broader access than what's actually
-- needed right now.
GRANT SELECT ON futbol.player_match_stats_nfl TO futbol_ro;
GRANT SELECT ON futbol.player_match_stats_nba TO futbol_ro;
GRANT SELECT ON futbol.team_match_stats_nfl TO futbol_ro;
