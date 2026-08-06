-- One-off migration for the already-running database (fresh installs get
-- this via schema.sql). Purely additive -- creates a new, empty table,
-- nothing existing is touched.
--
-- Backing store for a data-freshness indicator ("last successful run: 3h
-- ago" vs "this froze in June") and the eventual public status page.
-- Nothing writes to this table yet -- auto_slate.py/auto_grade.py/
-- ingestion scripts need a small wrapper to INSERT a row at start and
-- UPDATE status/finished_at/rows_written at the end. Not done here.
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
