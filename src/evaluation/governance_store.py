"""
Storage side of model governance (Todoist 6hqqP99w59C6F7vf, ADR-021).

An append-only event log per league/market cohort (table futbol.model_governance_events, migration 0046)
and thin helpers over it. The rules that matter are enforced by the database, not by this module: a
promotion needs a named approver, a rollback version, head-to-head evidence and 1,250 graded predictions,
and after a failure also a root cause approved AFTER the failure. Nothing here promotes automatically.

Not wired into slate generation yet: the slate jobs still serve one hard-coded model per cohort.
"""
from __future__ import annotations

from psycopg2.extras import Json

from evaluation.promotion import route_cohort

EVENT_TYPES = ("CHAMPION_ASSIGNED", "CHALLENGER_REGISTERED", "CHALLENGER_RETIRED", "PROMOTED",
               "RELEGATED", "SUSPENDED", "ROOT_CAUSE_APPROVED")


def record_event(conn, league: str, market: str, event_type: str, *, model_version_id: int | None = None,
                 rollback_model_version_id: int | None = None, approved_by: str | None = None,
                 root_cause_category: str | None = None, evidence: dict | None = None,
                 notes: str | None = None) -> int:
    """Append one event and commit. Raises psycopg2.Error if the database refuses it."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.model_governance_events
                   (league, market, event_type, model_version_id, rollback_model_version_id, approved_by,
                    root_cause_category, evidence, notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING event_id""",
            (league, market, event_type, model_version_id, rollback_model_version_id, approved_by,
             root_cause_category, Json(evidence or {}), notes))
        event_id = cur.fetchone()[0]
    conn.commit()
    return event_id


def cohort_state(conn, league: str, market: str) -> dict | None:
    """Current state of a cohort, or None if it has no champion history."""
    with conn.cursor() as cur:
        cur.execute("""SELECT state, champion_model_version_id, rollback_model_version_id, event_type, occurred_at
                       FROM futbol.v_cohort_state WHERE league = %s AND market = %s""", (league, market))
        row = cur.fetchone()
    if row is None:
        return None
    return {"state": row[0], "champion_model_version_id": row[1], "rollback_model_version_id": row[2],
            "last_event_type": row[3], "since": row[4]}


def cohort_route(conn, league: str, market: str) -> dict:
    """The routing decision for a cohort: serve the champion, or suspend. Shadows never publish."""
    state = cohort_state(conn, league, market)
    with conn.cursor() as cur:
        cur.execute("""SELECT model_version_id FROM futbol.v_cohort_shadows
                       WHERE league = %s AND market = %s ORDER BY model_version_id""", (league, market))
        shadows = [r[0] for r in cur.fetchall()]
    champion = None
    if state is not None and state["champion_model_version_id"] is not None:
        champion = {"version": state["champion_model_version_id"], "approved": True,
                    "reliable": state["state"] == "ACTIVE"}
    return route_cohort(champion, shadows)
