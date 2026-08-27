# Schema migrations

Numbered, ordered `.sql` files applied once each and tracked in a
`schema_migrations` table -- no external framework (alembic/yoyo),
matching this project's existing "no heavy dependencies" pattern.

## Adding a migration

1. Create `sql/migrations/NNNN_short_description.sql`, one more than
   the highest existing number.
2. Write it so it's safe to run against the live database exactly
   once (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF
   NOT EXISTS`, etc. where possible).
3. Also apply the same change to `sql/schema.sql`, which stays the
   canonical "create the whole schema from scratch" reference for a
   fresh database -- the two must be kept in sync by hand; nothing
   enforces this automatically.
4. Run `python scripts/migrate.py` against the real database
   (`FUTBOL_DSN`) to apply it and record it.

## Baseline

`0001_baseline.sql` is a deliberate no-op. Everything in `sql/schema.sql`
as of 2026-08-27, plus the pre-existing ad hoc one-off scripts in
`sql/` (`fix_duplicate_teams.sql`, `add_pipeline_runs_table.sql`,
etc.), was already live before this migrations convention existed --
those aren't renumbered into this sequence, since they already ran and
renumbering history retroactively would just be confusing. `0001`
exists only so `schema_migrations` has a starting point and new
migrations number from `0002` onward.
