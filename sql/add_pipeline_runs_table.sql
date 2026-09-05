-- One-off migration for the already-running database (fresh installs get
-- this via schema.sql). Purely additive -- creates a new, empty table,
-- nothing existing is touched.
--
-- Backing store for a data-freshness indicator ("last successful run: 3h
-- ago" vs "this froze in June") and the eventual public status page.
-- src/ops/pipeline_run.py (track_run()) writes to it from auto_slate.py,
-- auto_grade.py, and api_football.py's backfill entrypoint; api/main.py's
-- GET /pipeline-status reads it for the footer's freshness line.
--
-- This schema has no ALTER DEFAULT PRIVILEGES set up (checked live: none
-- configured for futbol.*), so every new table needs an explicit GRANT to
-- futbol_ro or the read-only API breaks on it with InsufficientPrivilege --
-- found the hard way when /pipeline-status 500'd right after deploy.
--
--     psql "$FUTBOL_DSN" -f sql/add_pipeline_runs_table.sql

CREATE TABLE IF NOT EXISTS futbol.pipeline_runs (
    run_id        BIGSERIAL PRIMARY KEY,
    job_name      TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed')),
    rows_written  INT,
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_job ON futbol.pipeline_runs (job_name, started_at DESC);
GRANT SELECT ON futbol.pipeline_runs TO futbol_ro;
