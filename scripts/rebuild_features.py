"""
Rebuilds team_match_features from sql/features.sql. Meant to run as the
last step of futbol-nightly-refresh, right after ingestion -- see
sql/features.sql's own header: "Re-runnable... Run after every
ingestion batch." Nothing was actually enforcing that; this is that
enforcement.

    python scripts/rebuild_features.py
"""
import os
import sys

import psycopg2

from ops.json_logging import configure_json_logging
from ops.pipeline_run import track_run

log = configure_json_logging("rebuild_features")

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
FEATURES_SQL = os.path.join(
    os.path.dirname(__file__), "..", "sql", "features.sql"
)


def main():
    with open(FEATURES_SQL) as f:
        sql = f.read()

    with track_run("rebuild_features") as set_rows_written:
        conn = psycopg2.connect(DSN)
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute("SET search_path TO futbol")
                cur.execute("SELECT COUNT(*) FROM team_match_features")
                n_team = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM player_match_features")
                n_player = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM referee_match_features")
                n_referee = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        set_rows_written(n_team + n_player + n_referee)
        log.info("rebuild_features done", extra={
            "n_team_match_features": n_team,
            "n_player_match_features": n_player,
            "n_referee_match_features": n_referee,
        })


if __name__ == "__main__":
    sys.exit(main())
