"""
The prediction ledger's guarantees, tested against a real Postgres.

The README's central claim is that once a prediction is written it cannot be
edited or deleted, "even by the system itself", and that every prediction is
locked before kickoff. Those guarantees live in database triggers, so the only
way to verify them is to try to violate them.
"""
from datetime import timedelta

import pytest

pytestmark = pytest.mark.integration

INSERT = """
INSERT INTO futbol.predictions
    (match_id, model_version_id, market, subject_team_id, subject_player_id,
     statement, line, side, probability, locked_at)
VALUES (%(match_id)s, %(model_version_id)s, %(market)s, %(subject_team_id)s,
        %(subject_player_id)s, %(statement)s, %(line)s, %(side)s,
        %(probability)s, %(locked_at)s)
RETURNING prediction_id
"""


def _row(fx, **overrides):
    row = {
        "match_id": fx["match_id"],
        "model_version_id": fx["model_version_id"],
        "market": "1X2",
        "subject_team_id": fx["home_team_id"],
        "subject_player_id": None,
        "statement": "Test Home FC win",
        "line": None,
        "side": "home",
        "probability": 0.61,
        "locked_at": fx["kickoff"] - timedelta(hours=6),
    }
    row.update(overrides)
    return row


def _insert(db, fx, **overrides):
    with db.cursor() as cur:
        cur.execute(INSERT, _row(fx, **overrides))
        return cur.fetchone()[0]


# ---------- immutability ----------

def test_prediction_can_be_written_before_kickoff(db, fixture_row):
    assert _insert(db, fixture_row) > 0


def test_triggers_do_not_depend_on_the_callers_search_path(db, fixture_row):
    """
    Regression test. enforce_pre_kickoff() used to read an unqualified
    `matches`; PL/pgSQL resolves that at execution time against the caller's
    search_path, so every client connecting with the default failed with
    'relation "matches" does not exist' on any prediction insert.
    """
    with db.cursor() as cur:
        cur.execute("SHOW search_path")
        assert "futbol" not in cur.fetchone()[0], (
            "test connection must not have futbol on its search_path, "
            "or this test cannot detect the defect it exists to catch"
        )
    assert _insert(db, fixture_row) > 0


def test_predictions_cannot_be_updated(db, fixture_row):
    pid = _insert(db, fixture_row)
    with pytest.raises(Exception, match="immutable"):
        with db.cursor() as cur:
            cur.execute(
                "UPDATE futbol.predictions SET probability = 0.99 WHERE prediction_id = %s",
                (pid,))


def test_predictions_cannot_be_deleted(db, fixture_row):
    pid = _insert(db, fixture_row)
    with pytest.raises(Exception, match="immutable"):
        with db.cursor() as cur:
            cur.execute("DELETE FROM futbol.predictions WHERE prediction_id = %s", (pid,))


def test_prediction_survives_the_attempts(db, fixture_row):
    pid = _insert(db, fixture_row)
    for stmt, args in (
        ("UPDATE futbol.predictions SET probability = 0.99 WHERE prediction_id = %s", (pid,)),
        ("DELETE FROM futbol.predictions WHERE prediction_id = %s", (pid,)),
    ):
        with pytest.raises(Exception):
            with db.cursor() as cur:
                cur.execute(stmt, args)
    with db.cursor() as cur:
        cur.execute(
            "SELECT probability FROM futbol.predictions WHERE prediction_id = %s", (pid,))
        assert float(cur.fetchone()[0]) == pytest.approx(0.61)


# ---------- pre-kickoff locking ----------

def test_prediction_locked_after_kickoff_is_rejected(db, fixture_row):
    with pytest.raises(Exception, match="locked after kickoff"):
        _insert(db, fixture_row, locked_at=fixture_row["kickoff"] + timedelta(minutes=1))


def test_prediction_locked_exactly_at_kickoff_is_rejected(db, fixture_row):
    """The trigger uses >=, so kickoff itself is too late."""
    with pytest.raises(Exception, match="locked after kickoff"):
        _insert(db, fixture_row, locked_at=fixture_row["kickoff"])


def test_prediction_locked_one_second_before_kickoff_is_accepted(db, fixture_row):
    assert _insert(db, fixture_row,
                   locked_at=fixture_row["kickoff"] - timedelta(seconds=1)) > 0


# ---------- probability domain ----------

@pytest.mark.parametrize("bad", [0, 1, -0.1, 1.5])
def test_probability_must_be_strictly_between_zero_and_one(db, fixture_row, bad):
    with pytest.raises(Exception):
        _insert(db, fixture_row, probability=bad)


# ---------- natural key ----------

def test_duplicate_prediction_is_rejected_by_natural_key(db, fixture_row):
    """
    Regression test for the NULLS DISTINCT defect. This row has a NULL
    subject_player_id and a NULL line, which under the original plain UNIQUE
    constraint meant it could never conflict with anything.
    """
    _insert(db, fixture_row)
    with pytest.raises(Exception):
        _insert(db, fixture_row)


def test_duplicate_with_no_nulls_in_key_is_rejected(db, fixture_row):
    kwargs = dict(market="CORNERS", side="over", line=4.5,
                  subject_team_id=fixture_row["home_team_id"],
                  subject_player_id=fixture_row["player_id"])
    _insert(db, fixture_row, **kwargs)
    with pytest.raises(Exception):
        _insert(db, fixture_row, **kwargs)


@pytest.mark.parametrize("shape", [
    dict(market="BTTS", side="yes", line=None,
         subject_team_id=None, subject_player_id=None),
    dict(market="TOTAL_GOALS", side="over", line=2.5,
         subject_team_id=None, subject_player_id=None),
    dict(market="PLAYER_GOALS", side="over", line=0.5, subject_team_id=None),
])
def test_every_null_bearing_prediction_shape_is_deduplicated(db, fixture_row, shape):
    """
    The original constraint failed for all of these. Cover each real shape
    rather than trusting that one example generalises.
    """
    if shape.get("subject_player_id", "unset") == "unset" and shape["market"].startswith("PLAYER"):
        shape = {**shape, "subject_player_id": fixture_row["player_id"]}
    _insert(db, fixture_row, **shape)
    with pytest.raises(Exception):
        _insert(db, fixture_row, **shape)


def test_distinct_predictions_are_still_allowed(db, fixture_row):
    """The key must not over-collapse: differing side, line, or subject are
    genuinely different claims and all must persist."""
    _insert(db, fixture_row, market="TOTAL_GOALS", side="over", line=2.5,
            subject_team_id=None)
    _insert(db, fixture_row, market="TOTAL_GOALS", side="under", line=2.5,
            subject_team_id=None)
    _insert(db, fixture_row, market="TOTAL_GOALS", side="over", line=3.5,
            subject_team_id=None)
    _insert(db, fixture_row, market="CORNERS", side="over", line=4.5,
            subject_team_id=fixture_row["home_team_id"])
    _insert(db, fixture_row, market="CORNERS", side="over", line=4.5,
            subject_team_id=fixture_row["away_team_id"])
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM futbol.predictions")
        assert cur.fetchone()[0] == 5


def test_null_subject_does_not_collide_with_a_real_subject(db, fixture_row):
    """The COALESCE sentinel must not make NULL equal to a real id."""
    _insert(db, fixture_row, market="CORNERS", side="over", line=4.5,
            subject_team_id=None)
    _insert(db, fixture_row, market="CORNERS", side="over", line=4.5,
            subject_team_id=fixture_row["home_team_id"])
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM futbol.predictions")
        assert cur.fetchone()[0] == 2


def test_persist_slate_is_idempotent(db, fixture_row):
    """
    Exercises the real writer, not just the index: persist_slate's docstring
    claims a re-run inserts only genuinely new rows.
    """
    from predictions.generator import Inference, persist_slate

    slate = [
        Inference(market="1X2", statement="Test Home FC win", line=None,
                  side="home", probability=0.61,
                  subject_team_id=fixture_row["home_team_id"]),
        Inference(market="BTTS", statement="Both teams to score", line=None,
                  side="yes", probability=0.55),
        Inference(market="TOTAL_GOALS", statement="Over 2.5 goals", line=2.5,
                  side="over", probability=0.52),
    ]
    first = persist_slate(db, fixture_row["match_id"],
                          fixture_row["model_version_id"], slate)
    second = persist_slate(db, fixture_row["match_id"],
                           fixture_row["model_version_id"], slate)
    assert first == 3
    assert second == 0
