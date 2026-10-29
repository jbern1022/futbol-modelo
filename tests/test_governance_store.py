"""
Model-governance storage (Todoist 6hqqP99w59C6F7vf, ADR-021): an append-only event log per league/market
cohort, a derived current-state view, and DB-enforced rules: a promotion needs a named approver, a rollback
version, head-to-head evidence and 1,250 graded predictions; after a failure (relegation or suspension) it
also needs an approved root cause recorded AFTER the failure. Events are immutable.

Runs against a THROWAWAY Postgres (FUTBOL_TEST_DSN, schema.sql already applied); skipped otherwise.
Events are committed (as in production) and immutable, so every test uses its own cohort.
"""
import os
import uuid

import psycopg2
import pytest

from evaluation.governance_store import cohort_route, cohort_state, record_event

DSN = os.environ.get("FUTBOL_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_TEST_DSN not set (throwaway database)")

H2H = {"head_to_head": {"verdict": "CHALLENGER_AHEAD"}, "challenger_graded_n": 1300}


@pytest.fixture
def db():
    conn = psycopg2.connect(DSN)
    cohort = (f"T{uuid.uuid4().hex[:8]}", "CORNERS")
    with conn.cursor() as cur:
        ids = []
        for tag in ("champ", "chall", "chall2"):
            cur.execute("INSERT INTO futbol.model_versions (model_name, version_tag) VALUES (%s,%s) "
                        "RETURNING model_version_id", (f"gov_{cohort[0]}", tag))
            ids.append(cur.fetchone()[0])
    conn.commit()
    yield conn, cohort, ids
    conn.rollback()
    conn.close()


def _assign(conn, cohort, mv):
    return record_event(conn, *cohort, "CHAMPION_ASSIGNED", model_version_id=mv, approved_by="joe")


def test_no_events_means_no_champion_and_a_suspended_route(db):
    conn, cohort, _ = db
    assert cohort_state(conn, *cohort) is None
    r = cohort_route(conn, *cohort)
    assert r["action"] == "SUSPEND_PRIMARY" and r["serve"] is None


def test_assigned_champion_is_served_and_shadows_are_listed_but_never_publish(db):
    conn, cohort, (champ, chall, _) = db
    _assign(conn, cohort, champ)
    record_event(conn, *cohort, "CHALLENGER_REGISTERED", model_version_id=chall)
    assert cohort_state(conn, *cohort)["state"] == "ACTIVE"
    r = cohort_route(conn, *cohort)
    assert (r["action"], r["serve"], r["shadow_versions"], r["shadows_publish"]) == (
        "SERVE_CHAMPION", champ, [chall], False)


def test_retired_challengers_drop_out_of_the_shadow_list(db):
    conn, cohort, (champ, chall, chall2) = db
    _assign(conn, cohort, champ)
    record_event(conn, *cohort, "CHALLENGER_REGISTERED", model_version_id=chall)
    record_event(conn, *cohort, "CHALLENGER_REGISTERED", model_version_id=chall2)
    record_event(conn, *cohort, "CHALLENGER_RETIRED", model_version_id=chall)
    assert cohort_route(conn, *cohort)["shadow_versions"] == [chall2]


def test_a_complete_promotion_replaces_the_champion_and_records_the_rollback(db):
    conn, cohort, (champ, chall, _) = db
    _assign(conn, cohort, champ)
    record_event(conn, *cohort, "PROMOTED", model_version_id=chall, approved_by="joe",
                 rollback_model_version_id=champ, evidence=H2H)
    s = cohort_state(conn, *cohort)
    assert s["champion_model_version_id"] == chall and s["rollback_model_version_id"] == champ


@pytest.mark.parametrize("override,why", [
    ({"approved_by": None}, "approver"),
    ({"rollback_model_version_id": None}, "rollback"),
    ({"evidence": {"challenger_graded_n": 1300}}, "head_to_head"),
    ({"evidence": {"head_to_head": {}, "challenger_graded_n": 1249}}, "1250"),
    ({"evidence": {"head_to_head": {}}}, "graded"),
])
def test_the_database_refuses_an_incomplete_promotion(db, override, why):
    conn, cohort, (champ, chall, _) = db
    _assign(conn, cohort, champ)
    fields = dict(model_version_id=chall, approved_by="joe", rollback_model_version_id=champ, evidence=H2H)
    fields.update(override)
    with pytest.raises(psycopg2.Error):
        record_event(conn, *cohort, "PROMOTED", **fields)
    conn.rollback()
    assert cohort_state(conn, *cohort)["champion_model_version_id"] == champ, why


def test_after_a_relegation_the_cohort_is_suspended_and_shadows_do_not_stand_in(db):
    conn, cohort, (champ, chall, _) = db
    _assign(conn, cohort, champ)
    record_event(conn, *cohort, "CHALLENGER_REGISTERED", model_version_id=chall)
    record_event(conn, *cohort, "RELEGATED", model_version_id=champ, notes="confirmed failure at 1,300 predictions")
    assert cohort_state(conn, *cohort)["state"] == "SUSPENDED"
    r = cohort_route(conn, *cohort)
    assert r["action"] == "SUSPEND_PRIMARY" and r["serve"] is None and r["shadows_publish"] is False


def test_promotion_after_a_failure_needs_a_root_cause_approved_after_it(db):
    conn, cohort, (champ, chall, _) = db
    _assign(conn, cohort, champ)
    record_event(conn, *cohort, "RELEGATED", model_version_id=champ, notes="failed")
    promo = dict(model_version_id=chall, approved_by="joe", rollback_model_version_id=champ, evidence=H2H)
    with pytest.raises(psycopg2.Error, match="root cause"):
        record_event(conn, *cohort, "PROMOTED", **promo)
    conn.rollback()
    record_event(conn, *cohort, "ROOT_CAUSE_APPROVED", approved_by="joe", root_cause_category="data_shift",
                 notes="MLS xG missing at predict time")
    record_event(conn, *cohort, "PROMOTED", **promo)
    s = cohort_state(conn, *cohort)
    assert s["state"] == "ACTIVE" and s["champion_model_version_id"] == chall


def test_a_root_cause_from_before_the_failure_does_not_count(db):
    conn, cohort, (champ, chall, _) = db
    _assign(conn, cohort, champ)
    record_event(conn, *cohort, "ROOT_CAUSE_APPROVED", approved_by="joe", root_cause_category="old")
    record_event(conn, *cohort, "SUSPENDED", notes="new failure")
    with pytest.raises(psycopg2.Error, match="root cause"):
        record_event(conn, *cohort, "PROMOTED", model_version_id=chall, approved_by="joe",
                     rollback_model_version_id=champ, evidence=H2H)
    conn.rollback()


def test_events_are_immutable(db):
    conn, cohort, (champ, _, _) = db
    eid = _assign(conn, cohort, champ)
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="immutable"):
            cur.execute("UPDATE futbol.model_governance_events SET approved_by = 'x' WHERE event_id = %s", (eid,))
    conn.rollback()
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="immutable"):
            cur.execute("DELETE FROM futbol.model_governance_events WHERE event_id = %s", (eid,))
    conn.rollback()


def test_unknown_event_types_are_rejected(db):
    conn, cohort, (champ, _, _) = db
    with pytest.raises(psycopg2.Error):
        record_event(conn, *cohort, "AUTO_PROMOTED", model_version_id=champ, approved_by="joe")
    conn.rollback()
