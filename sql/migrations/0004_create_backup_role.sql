-- Dedicated backup role. futbol_ro is scoped to exactly the ~15
-- tables/views the API serves (per-table GRANTs, not schema-wide) --
-- fine for the API, wrong for a backup, which needs everything.
-- pg_read_all_data is a builtin PostgreSQL role (since PG14) granting
-- SELECT on every table/view/sequence in every schema, including
-- tables created later -- no per-table GRANT bookkeeping needed, and
-- it can never write, matching the same least-privilege reasoning
-- documented for futbol_ro (see api/main.py's module docstring).
--
-- The password below is a placeholder -- set immediately after this
-- migration runs via a direct, non-committed ALTER ROLE, never stored
-- in git. See sql/migrations/README.md and CLAUDE.md's Credentials
-- section.

CREATE ROLE futbol_backup LOGIN PASSWORD 'CHANGE_ME_SET_DIRECTLY_AFTER_MIGRATION' CONNECTION LIMIT 3;
GRANT pg_read_all_data TO futbol_backup;
