-- Weather as a model feature: first prerequisite piece. No venue/
-- stadium location data existed anywhere in this schema before this
-- (checked directly) -- weather can't be looked up for a match without
-- knowing where it was played. City-level coordinates (not exact
-- stadium geocoding) are precise enough for weather purposes; it
-- doesn't meaningfully vary at football-stadium scale within a city.
--
-- Sourced from API-Football's /teams endpoint (venue.city, already
-- fetched alongside team data this project ingests anyway) geocoded
-- via Open-Meteo's free geocoding API (no key required) -- see
-- scripts/backfill_team_venues.py.
CREATE TABLE IF NOT EXISTS team_venues (
    team_id     INT PRIMARY KEY REFERENCES teams(team_id),
    venue_name  TEXT,
    city        TEXT,
    country     TEXT,
    latitude    NUMERIC(8,5),
    longitude   NUMERIC(8,5),
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
