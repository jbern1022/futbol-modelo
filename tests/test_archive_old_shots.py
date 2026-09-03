"""
Regression test for the season-ranking query in
scripts/archive_old_shots.py (SEASONS_TO_ARCHIVE_SQL) -- decides the
shots table's retention policy (open question, per Todoist): keep the
last N completed seasons per league, archive the rest.

Verified in isolation against a synthetic league/season set inside one
transaction that's always rolled back, so it doesn't depend on (or
affect) however many real seasons already exist for any real league.
"""
import os
import sys

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from archive_old_shots import SEASONS_TO_ARCHIVE_SQL

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def test_keeps_last_n_completed_seasons_only(conn):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO futbol.leagues (code, name)
           VALUES ('TEST_ARCHIVE_LEAGUE', 'Test Archive League')
           RETURNING league_id""")
    league_id = cur.fetchone()[0]

    # Five completed seasons, oldest to newest, plus one still in
    # progress (no end_date) -- the in-progress one must never be
    # flagged regardless of --keep.
    season_ids = {}
    for label, start, end in [
        ("2020-21", "2020-08-01", "2021-05-31"),
        ("2021-22", "2021-08-01", "2022-05-31"),
        ("2022-23", "2022-08-01", "2023-05-31"),
        ("2023-24", "2023-08-01", "2024-05-31"),
        ("2024-25", "2024-08-01", "2025-05-31"),
    ]:
        cur.execute(
            """INSERT INTO futbol.seasons (league_id, label, start_date, end_date)
               VALUES (%s, %s, %s, %s) RETURNING season_id""",
            (league_id, label, start, end))
        season_ids[label] = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label, start_date, end_date)
           VALUES (%s, %s, %s, NULL) RETURNING season_id""",
        (league_id, "2025-26", "2025-08-01"))
    in_progress_id = cur.fetchone()[0]

    cur.execute(SEASONS_TO_ARCHIVE_SQL, (3,))
    flagged = {row[0] for row in cur.fetchall()}

    # Only this league's two oldest completed seasons should be flagged
    # when keeping the last 3 -- the in-progress season must never
    # appear regardless.
    assert season_ids["2020-21"] in flagged
    assert season_ids["2021-22"] in flagged
    assert season_ids["2022-23"] not in flagged
    assert season_ids["2023-24"] not in flagged
    assert season_ids["2024-25"] not in flagged
    assert in_progress_id not in flagged


def test_keep_zero_flags_all_completed_seasons(conn):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO futbol.leagues (code, name)
           VALUES ('TEST_ARCHIVE_LEAGUE_2', 'Test Archive League 2')
           RETURNING league_id""")
    league_id = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label, start_date, end_date)
           VALUES (%s, '2024-25', '2024-08-01', '2025-05-31')
           RETURNING season_id""",
        (league_id,))
    completed_id = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label, start_date, end_date)
           VALUES (%s, '2025-26', '2025-08-01', NULL)
           RETURNING season_id""",
        (league_id,))
    in_progress_id = cur.fetchone()[0]

    cur.execute(SEASONS_TO_ARCHIVE_SQL, (0,))
    flagged = {row[0] for row in cur.fetchall()}

    assert completed_id in flagged
    assert in_progress_id not in flagged
