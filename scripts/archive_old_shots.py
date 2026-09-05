"""
Moves shots rows older than the last N completed seasons per league
into shots_archive (not deleted -- this data feeds the planned custom
xG model, see Todoist). Dry-run by default; pass --execute to commit.

    python scripts/archive_old_shots.py                # dry run, default keep=3
    python scripts/archive_old_shots.py --execute       # actually move rows
    python scripts/archive_old_shots.py --keep 2 --execute
"""
import argparse
import os

import psycopg2

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# "Completed" means the season has an end_date in the past -- a season
# still in progress (end_date NULL or in the future) is never eligible,
# regardless of --keep.
SEASONS_TO_ARCHIVE_SQL = """
WITH ranked_seasons AS (
    SELECT season_id, league_id, label, end_date,
           ROW_NUMBER() OVER (PARTITION BY league_id ORDER BY end_date DESC) AS rn
    FROM futbol.seasons
    WHERE end_date IS NOT NULL AND end_date < CURRENT_DATE
)
SELECT season_id, league_id, label, end_date FROM ranked_seasons WHERE rn > %s
"""

COUNT_SHOTS_SQL = """
SELECT COUNT(*) FROM futbol.shots s
JOIN futbol.matches m ON m.match_id = s.match_id
WHERE m.season_id = ANY(%s)
"""

ARCHIVE_SQL = """
INSERT INTO futbol.shots_archive
    (shot_id, match_id, player_id, team_id, minute, x, y, situation, body_part, result, source_xg)
SELECT s.shot_id, s.match_id, s.player_id, s.team_id, s.minute, s.x, s.y,
       s.situation, s.body_part, s.result, s.source_xg
FROM futbol.shots s
JOIN futbol.matches m ON m.match_id = s.match_id
WHERE m.season_id = ANY(%s)
ON CONFLICT (shot_id) DO NOTHING
"""

DELETE_SQL = """
DELETE FROM futbol.shots s
USING futbol.matches m
WHERE s.match_id = m.match_id AND m.season_id = ANY(%s)
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=3,
                    help="Number of most recent completed seasons to keep per league (default 3)")
    ap.add_argument("--execute", action="store_true",
                    help="Actually move rows. Without this flag, only reports what would happen.")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(SEASONS_TO_ARCHIVE_SQL, (args.keep,))
            old_seasons = cur.fetchall()

            if not old_seasons:
                print(f"No completed seasons beyond the last {args.keep} per league -- nothing to archive.")
                return

            season_ids = [row[0] for row in old_seasons]
            print(f"Seasons eligible for archiving (beyond the last {args.keep} completed per league):")
            for season_id, league_id, label, end_date in old_seasons:
                print(f"  league_id={league_id} season={label} (ended {end_date})")

            cur.execute(COUNT_SHOTS_SQL, (season_ids,))
            n_shots = cur.fetchone()[0]
            print(f"{n_shots} shot row(s) would be archived.")

            if not args.execute:
                print("Dry run only -- pass --execute to actually move these rows.")
                return

            cur.execute(ARCHIVE_SQL, (season_ids,))
            n_archived = cur.rowcount
            cur.execute(DELETE_SQL, (season_ids,))
            n_deleted = cur.rowcount
            conn.commit()
            print(f"Archived {n_archived} row(s), deleted {n_deleted} row(s) from the live shots table.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
