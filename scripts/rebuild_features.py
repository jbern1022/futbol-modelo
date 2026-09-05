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

from ops.pipeline_run import track_run

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
            conn.commit()
        finally:
            conn.close()
        set_rows_written(n_team + n_player)
        print(f"rebuild_features done: {n_team} rows in team_match_features, "
              f"{n_player} rows in player_match_features")


if __name__ == "__main__":
    sys.exit(main())
