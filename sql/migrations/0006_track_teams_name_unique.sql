-- Reconciles real schema drift found while researching the
-- teams.name incident for a writeup: sql/fix_duplicate_teams.sql
-- (2026-07-10) added `ALTER TABLE teams ADD CONSTRAINT
-- teams_name_unique UNIQUE (name)` directly against the live database,
-- but schema.sql was never updated to match -- a fresh database built
-- from schema.sql alone would be missing this constraint entirely,
-- and upsert_team()'s `ON CONFLICT (name) DO NOTHING`
-- (src/ingestion/loader.py) requires a matching unique constraint to
-- function at all. Without it, the very first team upsert on a fresh
-- database would crash with "there is no unique or exclusion
-- constraint matching the ON CONFLICT specification" -- silently
-- reintroducing the exact bug this constraint exists to prevent.
--
-- This migration is a no-op on the live database (the constraint
-- already exists) -- it exists so schema.sql and a fresh database
-- match live reality.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'teams_name_unique'
    ) THEN
        ALTER TABLE teams ADD CONSTRAINT teams_name_unique UNIQUE (name);
    END IF;
END $$;
