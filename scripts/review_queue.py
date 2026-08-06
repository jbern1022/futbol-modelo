"""
Prints unresolved entries from futbol.ingest_review -- possible-duplicate
players and other ingestion ambiguities entities.py flags for a human to
check, that nothing currently surfaces anywhere else.

    python scripts/review_queue.py
"""
import os

import psycopg2
import psycopg2.extras

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


def main():
    conn = psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT review_id, kind, detail, created_at
                   FROM futbol.ingest_review
                   WHERE NOT resolved
                   ORDER BY created_at"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("ingest_review: nothing pending.")
        return

    print(f"ingest_review: {len(rows)} unresolved entr{'y' if len(rows) == 1 else 'ies'}")
    for row in rows:
        print(f"  [{row['review_id']}] {row['created_at']:%Y-%m-%d} {row['kind']}: {row['detail']}")


if __name__ == "__main__":
    main()
