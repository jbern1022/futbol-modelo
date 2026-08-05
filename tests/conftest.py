"""
Integration-test fixtures.

Builds a throwaway schema from sql/schema.sql against a real Postgres, so the
triggers and constraints under test are the ones the project actually ships.
Never touches a production database: set FUTBOL_TEST_DSN to a scratch server
(CI runs one as a service container). Tests skip cleanly when it is unset.
"""
import os
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO_ROOT / "sql" / "schema.sql"
TEST_DSN = os.environ.get("FUTBOL_TEST_DSN")


@pytest.fixture(scope="session")
def db():
    if not TEST_DSN:
        pytest.skip("FUTBOL_TEST_DSN not set — skipping integration tests")
    psycopg2 = pytest.importorskip("psycopg2")

    conn = psycopg2.connect(TEST_DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS futbol CASCADE;")
        cur.execute(SCHEMA_SQL.read_text())
        # schema.sql opens with `SET search_path TO futbol`, which would
        # otherwise persist for this whole session and mask any object that
        # depends on the caller's search_path. Application code connects with
        # the default and fully qualifies its tables, so tests must too.
        cur.execute("RESET search_path;")
    yield conn
    conn.close()


@pytest.fixture
def fixture_row(db):
    """
    A minimal league/season/teams/player/match/model_version chain, with a
    kickoff in the future so pre-kickoff locking can be tested from both sides.

    Cleanup uses TRUNCATE rather than DELETE: predictions carries a BEFORE
    DELETE trigger that raises unconditionally, so DELETE cannot clear it.
    TRUNCATE fires only TRUNCATE triggers, so it bypasses that guard — which
    is exactly why it must never be pointed at production.
    """
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE futbol.prediction_grades, futbol.predictions, futbol.matches "
            "RESTART IDENTITY CASCADE;")

        cur.execute(
            """INSERT INTO futbol.leagues (code, name) VALUES ('TEST','Test League')
               ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
               RETURNING league_id""")
        league_id = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO futbol.seasons (league_id, label) VALUES (%s,'2025-26')
               ON CONFLICT (league_id, label) DO UPDATE SET label = EXCLUDED.label
               RETURNING season_id""", (league_id,))
        season_id = cur.fetchone()[0]

        team_ids = []
        for name in ("Test Home FC", "Test Away FC"):
            cur.execute("SELECT team_id FROM futbol.teams WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                team_ids.append(row[0])
            else:
                cur.execute(
                    "INSERT INTO futbol.teams (name) VALUES (%s) RETURNING team_id",
                    (name,))
                team_ids.append(cur.fetchone()[0])
        home_id, away_id = team_ids

        cur.execute("SELECT player_id FROM futbol.players WHERE full_name = %s",
                    ("Test Player",))
        row = cur.fetchone()
        if row:
            player_id = row[0]
        else:
            cur.execute(
                """INSERT INTO futbol.players (full_name, position)
                   VALUES ('Test Player','FW') RETURNING player_id""")
            player_id = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO futbol.matches
                 (season_id, home_team_id, away_team_id, kickoff_utc, status)
               VALUES (%s,%s,%s,%s,'scheduled') RETURNING match_id""",
            (season_id, home_id, away_id, kickoff))
        match_id = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO futbol.model_versions (model_name, version_tag)
               VALUES ('test_model','v1')
               ON CONFLICT (model_name, version_tag) DO UPDATE
                 SET model_name = EXCLUDED.model_name
               RETURNING model_version_id""")
        model_version_id = cur.fetchone()[0]

    return {
        "match_id": match_id,
        "model_version_id": model_version_id,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "player_id": player_id,
        "kickoff": kickoff,
    }
