"""
Bookkeeping for futbol.pipeline_runs -- backs the "last successful run"
freshness indicator instead of silent staleness (see: predictions going
16 days stale with no signal anywhere that anything was wrong).

Uses its own connection, separate from whatever the wrapped job is doing,
so a job's own DB errors (or a transaction left dirty by an uncaught
exception) can't also take out the bookkeeping write that's supposed to
report that failure.
"""
from __future__ import annotations

import logging
import os
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2

log = logging.getLogger(__name__)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


@contextmanager
def track_run(job_name: str):
    """
    with track_run("auto_slate:MLS") as set_rows_written:
        ...
        set_rows_written(42)

    Records a 'running' row at entry and 'success'/'failed' at exit.
    Bookkeeping failures are logged, never raised -- a broken freshness
    indicator must never be the reason the actual job fails.
    """
    run_id = None
    try:
        conn = psycopg2.connect(DSN)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO futbol.pipeline_runs (job_name, started_at, status) "
                "VALUES (%s, %s, 'running') RETURNING run_id",
                (job_name, datetime.now(timezone.utc)))
            run_id = cur.fetchone()[0]
    except Exception:
        log.warning("pipeline_run tracking unavailable (insert failed)", exc_info=True)
        conn = None

    state = {"rows_written": None}

    def set_rows_written(n):
        state["rows_written"] = n

    try:
        yield set_rows_written
    except Exception:
        if conn is not None and run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE futbol.pipeline_runs SET status='failed', "
                        "finished_at=%s, rows_written=%s, detail=%s "
                        "WHERE run_id=%s",
                        (datetime.now(timezone.utc), state["rows_written"],
                         traceback.format_exc()[-2000:], run_id))
            except Exception:
                log.warning("pipeline_run tracking unavailable (failure update)", exc_info=True)
        raise
    else:
        if conn is not None and run_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE futbol.pipeline_runs SET status='success', "
                        "finished_at=%s, rows_written=%s WHERE run_id=%s",
                        (datetime.now(timezone.utc), state["rows_written"], run_id))
            except Exception:
                log.warning("pipeline_run tracking unavailable (success update)", exc_info=True)
    finally:
        if conn is not None:
            conn.close()


def record_model_version_history(cur, model_name: str, version_tag: str,
                                   training_window: str | None,
                                   params: str, train_metrics: str) -> None:
    """
    Append one snapshot row to futbol.model_versions_history (migration
    0027) alongside -- not instead of -- the caller's own model_versions
    upsert. model_versions itself is a "current pointer" per
    (model_name, version_tag): every write site here reuses a static
    version_tag (e.g. 'v1') on every retrain, so ON CONFLICT DO UPDATE
    silently overwrites yesterday's params/train_metrics with no history
    anywhere. Call this with the same cursor right after the
    model_versions INSERT so both land in the same transaction.
    """
    cur.execute(
        """INSERT INTO futbol.model_versions_history
             (model_name, version_tag, training_window, params, train_metrics)
           VALUES (%s,%s,%s,%s,%s)""",
        (model_name, version_tag, training_window, params, train_metrics))
