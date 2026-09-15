-- Root-cause fix for the bug patched three times one view at a time
-- (migrations 0012, 0018, 0020): the existing rule is
--   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA futbol
--     GRANT SELECT ON TABLES TO futbol_ro;
-- which only fires for objects created BY the `postgres` role. Every
-- migration actually runs as `futbol` (scripts/migrate.py connects with
-- FUTBOL_DSN), so every table/view a migration creates has never been
-- covered by that rule -- futbol_ro needs an explicit GRANT for each one,
-- forever, until this is fixed.
--
-- Adding the matching rule for the `futbol` role itself closes the gap
-- for anything created from here on. This does NOT retroactively grant
-- existing objects (that's what migrations 0005/0012/0018/0020 already
-- did) -- it only changes what happens on the NEXT CREATE TABLE/VIEW.
ALTER DEFAULT PRIVILEGES FOR ROLE futbol IN SCHEMA futbol
    GRANT SELECT ON TABLES TO futbol_ro;
