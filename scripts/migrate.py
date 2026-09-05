"""Applies sql/migrations/*.sql files in filename order that haven't
already been recorded in futbol.schema_migrations. No external
migration framework -- matches this project's existing "no heavy
dependencies" pattern. See sql/migrations/README.md.

Run:
    python scripts/migrate.py
"""
import glob
import os
import sys

import psycopg2

DSN = os.environ.get("FUTBOL_DSN")
if not DSN:
    sys.exit("FUTBOL_DSN not set")

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "sql", "migrations")


def ensure_tracking_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def applied_versions(cur):
    cur.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def main():
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO futbol")
            ensure_tracking_table(cur)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SET search_path TO futbol")
            done = applied_versions(cur)

        files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
        pending = [f for f in files if os.path.basename(f) not in done]

        if not pending:
            print("Up to date -- no pending migrations.")
            return

        for path in pending:
            name = os.path.basename(path)
            print(f"Applying {name}...")
            with open(path) as f:
                sql = f.read()
            with conn.cursor() as cur:
                cur.execute("SET search_path TO futbol")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (name,)
                )
            conn.commit()
            print("  -> applied.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
