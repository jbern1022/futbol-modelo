-- v_market_comparison (migration 0011) was created via scripts/migrate.py,
-- run as the app's own `futbol` role -- not covered by the ALTER DEFAULT
-- PRIVILEGES rule that only applies to objects the `postgres` role
-- creates (see migration 0005's comment, found the same way). Caught
-- live: GET /v1/odds-comparison 500'd in production with
-- psycopg2.errors.InsufficientPrivilege as soon as it was deployed.
GRANT SELECT ON futbol.v_market_comparison TO futbol_ro;
