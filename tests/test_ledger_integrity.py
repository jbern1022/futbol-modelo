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

@pytest.mark.xfail(
    strict=True,
    reason="predictions_natural_key is inert: Postgres UNIQUE defaults to NULLS "
           "DISTINCT and subject_player_id is NULL here, so the duplicate inserts "
           "cleanly. Same bug class as the teams.name constraint. Flip to passing "
           "with NULLS NOT DISTINCT (PG15+) or a COALESCE-based unique index.",
)
def test_duplicate_prediction_is_rejected_by_natural_key(db, fixture_row):
    _insert(db, fixture_row)
    with pytest.raises(Exception):
        _insert(db, fixture_row)


def test_duplicate_with_no_nulls_in_key_is_rejected(db, fixture_row):
    """
    Control for the xfail above: when every key column is non-NULL the
    constraint does work, which isolates NULL handling as the cause.
    """
    kwargs = dict(market="CORNERS", side="over", line=4.5,
                  subject_team_id=fixture_row["home_team_id"],
                  subject_player_id=fixture_row["player_id"])
    _insert(db, fixture_row, **kwargs)
    with pytest.raises(Exception):
        _insert(db, fixture_row, **kwargs)
