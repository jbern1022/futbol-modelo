-- v_petey_predictions (migration 0017) hit the exact same gap migration
-- 0012 already documented: a view created via scripts/migrate.py (as the
-- `futbol` role) isn't covered by the ALTER DEFAULT PRIVILEGES rule that
-- only applies to objects `postgres` creates. Caught the same way this
-- time too, before it ever reached production: a local SELECT against
-- v_petey_predictions using FUTBOL_RO_DSN 500'd with InsufficientPrivilege.
GRANT SELECT ON futbol.v_petey_predictions TO futbol_ro;

-- api/main.py is deliberately read-only (FUTBOL_RO_DSN, "can't write to
-- the ledger even in the event of a bug" per its own docstring) -- but
-- Petey's self-improving-FAQ-loop logging (petey_queries) needs an
-- INSERT path from the API. Narrow, explicit exception: INSERT only,
-- no SELECT/UPDATE/DELETE, and petey_queries isn't the prediction
-- ledger -- this doesn't weaken the invariant the read-only role exists
-- to protect.
GRANT INSERT ON futbol.petey_queries TO futbol_ro;
GRANT USAGE ON SEQUENCE futbol.petey_queries_query_id_seq TO futbol_ro;
