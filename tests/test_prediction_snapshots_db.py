"""
End-to-end against a THROWAWAY Postgres (FUTBOL_TEST_DSN; skipped when unset -- never
point it at production). Applies nothing itself: the database must already have
sql/schema.sql. Everything runs in a transaction that is rolled back.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from predictions.generator import Inference, persist_slate
from predictions.snapshot import build_snapshot, record_snapshots

DSN = os.environ.get("FUTBOL_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_TEST_DSN not set (throwaway database)")


@pytest.fixture
def conn():
    c = psycopg2.connect(DSN)
    yield c
    c.rollback()
    c.close()


def _seed(cur):
    # persist_slate and record_snapshots commit (as in production) and predictions are
    # immutable, so seed rows persist in the throwaway database: make every run unique.
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO futbol.leagues (code, name) VALUES (%s,'Test') RETURNING league_id", (f"T{tag}",))
    lid = cur.fetchone()[0]
    cur.execute("INSERT INTO futbol.seasons (league_id, label) VALUES (%s,'2026-27') RETURNING season_id", (lid,))
    sid = cur.fetchone()[0]
    ids = []
    for n in ("A", "B"):
        cur.execute("INSERT INTO futbol.teams (name) VALUES (%s) RETURNING team_id", (f"Team {n} {tag}",))
        ids.append(cur.fetchone()[0])
    ko = datetime.now(timezone.utc) + timedelta(days=2)
    cur.execute("""INSERT INTO futbol.matches (season_id, home_team_id, away_team_id, kickoff_utc)
                   VALUES (%s,%s,%s,%s) RETURNING match_id""", (sid, ids[0], ids[1], ko))
    mid = cur.fetchone()[0]
    cur.execute("""INSERT INTO futbol.model_versions (model_name, version_tag) VALUES ('t',%s)
                   RETURNING model_version_id""", (tag,))
    return mid, cur.fetchone()[0], ids, ko


def _slate(ids, ko, now):
    snap = build_snapshot(market="CORNERS", features={"corners_for_r5": 6.0, "rest_days": 6},
                          feature_cols=["corners_for_r5", "xg_for_r5", "rest_days", "is_home"], is_home=True,
                          cutoff=now, kickoff=ko, model_tag="v4",
                          form_meta={"inputs_through": now - timedelta(days=2), "n_games": 5, "window_days": 90})
    over = Inference("CORNERS", "A over 4.5", 4.5, "over", 0.6, ids[0])
    under = Inference("CORNERS", "A under 5.5", 5.5, "under", 0.6, ids[0])
    over.snapshot = under.snapshot = snap
    plain = Inference("1X2", "A win", None, "home", 0.5, ids[0])
    return [over, under, plain]


def test_snapshots_are_written_for_snapshotted_predictions_only_and_are_immutable(conn):
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        mid, mvid, ids, ko = _seed(cur)
    slate = _slate(ids, ko, now)
    assert persist_slate(conn, mid, mvid, slate) == 3
    assert record_snapshots(conn, mid, mvid, slate) == 2
    assert record_snapshots(conn, mid, mvid, slate) == 0  # re-run is a no-op
    with conn.cursor() as cur:
        cur.execute("""SELECT p.market, p.side, s.missing_features, s.feature_values->>'rest_days'
                       FROM futbol.prediction_snapshots s JOIN futbol.predictions p USING (prediction_id)
                       WHERE p.match_id = %s ORDER BY p.side""", (mid,))
        rows = cur.fetchall()
        assert [(r[0], r[1]) for r in rows] == [("CORNERS", "over"), ("CORNERS", "under")]
        assert rows[0][2] == ["xg_for_r5"] and rows[0][3] == "6"
        cur.execute("SAVEPOINT s")
        with pytest.raises(psycopg2.Error, match="immutable"):
            cur.execute("UPDATE futbol.prediction_snapshots SET n_games = 99 WHERE prediction_id IN "
                        "(SELECT prediction_id FROM futbol.predictions WHERE match_id = %s)", (mid,))
        cur.execute("ROLLBACK TO SAVEPOINT s")
        with pytest.raises(psycopg2.Error, match="immutable"):
            cur.execute("DELETE FROM futbol.prediction_snapshots WHERE prediction_id IN "
                        "(SELECT prediction_id FROM futbol.predictions WHERE match_id = %s)", (mid,))


def test_database_rejects_inputs_after_the_cutoff(conn):
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        mid, mvid, ids, ko = _seed(cur)
        cur.execute("""INSERT INTO futbol.predictions (match_id, model_version_id, market, statement, side, probability,
                       created_at, locked_at) VALUES (%s,%s,'1X2','A win','home',0.5,%s,%s) RETURNING prediction_id""",
                    (mid, mvid, now, now))
        pid = cur.fetchone()[0]
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("""INSERT INTO futbol.prediction_snapshots
                (prediction_id, schema_version, cutoff_at, kickoff_at, inputs_through, model_tag, feature_values)
                VALUES (%s,1,%s,%s,%s,'v4','{}')""", (pid, now, ko, now + timedelta(hours=1)))
