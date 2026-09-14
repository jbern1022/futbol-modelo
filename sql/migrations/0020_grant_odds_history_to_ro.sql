-- Same view-grant gap as migrations 0012 and 0018 -- v_odds_movement
-- (migration 0019) was created via scripts/migrate.py as the `futbol`
-- role, not covered by ALTER DEFAULT PRIVILEGES. Caught locally before
-- it ever reached production, third time this exact class of bug has
-- shown up -- worth fixing the root cause (whatever provisions futbol_ro)
-- rather than continuing to patch each new view one migration at a time.
GRANT SELECT ON futbol.v_odds_movement TO futbol_ro;
