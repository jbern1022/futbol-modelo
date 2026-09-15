"""
Cross-source reconciliation report: how much do FBref and API-Football
actually disagree on the same match's corners / shots-on-target, now
that both are recorded separately (migration 0025) instead of one
silently overwriting the other in team_match_stats?

No comparison data exists until BOTH sources have independently ingested
the same (match, team) -- this queries futbol.v_source_reconciliation,
which only includes rows where that's already true, so an empty report
right after this shipped is expected, not a bug: it fills in as the
normal nightly ingestion (which already runs both sources for the
leagues that have both) accumulates overlapping rows going forward.

    python scripts/report_source_reconciliation.py
"""
import os

import psycopg2

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


def main():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM futbol.v_source_reconciliation")
            n = cur.fetchone()[0]
            if n == 0:
                print("No overlapping (match, team) rows from both sources yet -- "
                      "expected right after this shipped. Re-run after the next "
                      "nightly ingestion accumulates some.")
                return

            for label, col in (("Corners", "corners"), ("Shots on target", "sot")):
                cur.execute(f"""
                    SELECT count(*), avg(abs({col}_diff)),
                           count(*) FILTER (WHERE {col}_diff = 0)
                    FROM futbol.v_source_reconciliation
                """)
                n, mean_abs_diff, n_exact = cur.fetchone()
                print(f"\n{label} (n={n}):")
                print(f"  mean |diff| = {mean_abs_diff:.2f}")
                print(f"  exact agreement: {n_exact}/{n} ({n_exact / n:.1%})")

            cur.execute("""
                SELECT match_id, team_id, corners_fbref, corners_api_football, corners_diff
                FROM futbol.v_source_reconciliation
                WHERE corners_diff != 0
                ORDER BY abs(corners_diff) DESC LIMIT 5
            """)
            rows = cur.fetchall()
            if rows:
                print("\nLargest corners disagreements:")
                for match_id, team_id, fb, af, diff in rows:
                    print(f"  match {match_id} team {team_id}: fbref={fb} api_football={af} (diff={diff:+d})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
