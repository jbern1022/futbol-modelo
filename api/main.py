"""
futbol-modelo portal API — read-only FastAPI backend serving fixtures,
slates, and the season scorecard from Postgres. Uses the futbol_ro role
(SELECT-only), never the main futbol user — this API can't write to the
ledger even in the event of a bug.

Run locally:
    uvicorn api.main:app --reload --port 8000

Endpoints:
    GET /fixtures?league=MLS&status=scheduled&days=21
    GET /fixtures/{match_id}/slate
    GET /scorecard?league=MLS
    GET /calibration?league=MLS
    POST /ask  {"market": "CORNERS", "league": "MLS"}
"""
import os
import time
from typing import Optional

import psycopg2
import psycopg2.extras
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

RO_DSN = os.environ.get(
    "FUTBOL_RO_DSN",
    "host=futbol-db dbname=futbol user=futbol_ro password=CHANGE_ME",
)
OLLAMA_URL = os.environ.get("FUTBOL_OLLAMA_URL", "http://192.168.4.48:11434")
OLLAMA_MODEL = "llama3.2:latest"
OLLAMA_TIMEOUT_SECONDS = 20  # ADR-005 hard cutoff

app = FastAPI(
    title="futbol-modelo API",
    description="Read-only access to fixtures, prediction slates, and "
                "calibration data for the futbol-modelo prediction system.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_conn():
    return psycopg2.connect(RO_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


@app.get("/")
def root():
    return {"service": "futbol-modelo API", "status": "ok",
            "endpoints": ["/fixtures", "/fixtures/{match_id}/slate",
                         "/scorecard", "/calibration", "/ask"]}


@app.get("/fixtures")
def list_fixtures(
    league: Optional[str] = Query(None, description="EPL, SERIE_A, MLS, or WC"),
    status: str = Query("scheduled", description="scheduled or final"),
    days: int = Query(21, description="Only fixtures within this many days"),
):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT m.match_id, l.code AS league, s.label AS season,
                       th.name AS home, ta.name AS away,
                       m.kickoff_utc, m.status,
                       m.home_goals, m.away_goals,
                       (SELECT COUNT(*) FROM futbol.predictions p
                        WHERE p.match_id = m.match_id) AS n_predictions
                FROM futbol.matches m
                JOIN futbol.teams th ON th.team_id = m.home_team_id
                JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                JOIN futbol.seasons s ON s.season_id = m.season_id
                JOIN futbol.leagues l ON l.league_id = s.league_id
                WHERE m.status = %s
                  AND m.kickoff_utc BETWEEN now() - interval '1 day'
                                        AND now() + (%s || ' days')::interval
            """
            params = [status, days]
            if league:
                query += " AND l.code = %s"
                params.append(league)
            query += " ORDER BY m.kickoff_utc"
            cur.execute(query, params)
            rows = cur.fetchall()
        return {"count": len(rows), "fixtures": rows}
    finally:
        conn.close()


@app.get("/fixtures/{match_id}/slate")
def get_slate(match_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.match_id, l.code AS league, th.name AS home,
                          ta.name AS away, m.kickoff_utc, m.status
                   FROM futbol.matches m
                   JOIN futbol.teams th ON th.team_id = m.home_team_id
                   JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                   JOIN futbol.seasons s ON s.season_id = m.season_id
                   JOIN futbol.leagues l ON l.league_id = s.league_id
                   WHERE m.match_id = %s""", (match_id,))
            fixture = cur.fetchone()
            if not fixture:
                raise HTTPException(status_code=404, detail="Fixture not found")

            cur.execute(
                """SELECT p.prediction_id, p.market, p.statement, p.side,
                          p.line, p.probability, p.locked_at,
                          tt.name AS subject_team,
                          pl.full_name AS subject_player,
                          g.outcome, g.actual_value
                   FROM futbol.predictions p
                   LEFT JOIN futbol.teams tt ON tt.team_id = p.subject_team_id
                   LEFT JOIN futbol.players pl ON pl.player_id = p.subject_player_id
                   LEFT JOIN futbol.prediction_grades g
                     ON g.prediction_id = p.prediction_id
                   WHERE p.match_id = %s
                   ORDER BY p.probability DESC""", (match_id,))
            predictions = cur.fetchall()
        return {"fixture": fixture, "predictions": predictions}
    finally:
        conn.close()


@app.get("/scorecard")
def scorecard(league: Optional[str] = Query(None)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = "SELECT * FROM futbol.v_season_scorecard"
            params = []
            if league:
                query += " WHERE league = %s"
                params.append(league)
            query += " ORDER BY league, season, market"
            cur.execute(query, params)
            rows = cur.fetchall()
        return {"count": len(rows), "scorecard": rows}
    finally:
        conn.close()


@app.get("/calibration")
def calibration(league: Optional[str] = Query(None)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = "SELECT * FROM futbol.v_calibration WHERE n >= 3"
            params = []
            if league:
                query += " AND league = %s"
                params.append(league)
            query += " ORDER BY league, market, avg_stated_prob"
            cur.execute(query, params)
            rows = cur.fetchall()
        return {"count": len(rows), "calibration": rows}
    finally:
        conn.close()


class AskRequest(BaseModel):
    market: str
    league: str


@app.post("/ask")
def ask_petey(req: AskRequest):
    """
    Petey v1 — first real slice. Per ADR-002/ADR-008: Ollama never sees
    raw rows or writes any query. This endpoint looks up one real,
    pre-computed aggregate and asks Ollama only to phrase that exact
    number as a sentence. Per ADR-007, flags small samples (n < 5).
    Per ADR-005, hard 20s timeout with a graceful, still-honest fallback.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM futbol.v_season_scorecard
                   WHERE market = %s AND league = %s""",
                (req.market, req.league))
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return {
            "answer": f"I don't have any graded predictions yet for "
                      f"{req.market} in {req.league}.",
            "n_predictions": 0,
            "small_sample": True,
        }

    n = row["n_predictions"]
    small_sample = n < 5
    hit_rate = float(row["hit_rate"])
    avg_confidence = float(row["avg_confidence"])

    summary = (
        f"Market: {row['market']}, League: {row['league']}, "
        f"Predictions graded: {n}, "
        f"Stated confidence: {avg_confidence * 100:.1f}%, "
        f"Realized hit rate: {hit_rate * 100:.1f}%."
    )
    prompt = (
        "You are Petey, a straightforward sports-analytics assistant. "
        "Turn the following stat summary into ONE short, plain-English "
        "sentence describing prediction accuracy for this market. "
        "'Hit rate' means the percentage of past predictions that turned "
        "out correct — it is NOT a literal count of goals, corners, or "
        "events. Do not add any numbers, teams, or facts not present "
        "in the summary below. Do not speculate.\n\n" + summary
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        answer = resp.json().get("response", "").strip()
        if not answer:
            raise ValueError("empty response")
    except Exception:
        answer = (
            f"{row['market']} predictions in {row['league']} have hit "
            f"{hit_rate * 100:.1f}% of the time across {n} graded "
            f"predictions."
        )

    result = {
        "answer": answer,
        "n_predictions": n,
        "hit_rate": hit_rate,
        "avg_confidence": avg_confidence,
        "small_sample": small_sample,
    }
    if small_sample:
        noun = "prediction" if n == 1 else "predictions"
        result["disclaimer"] = f"Based on only {n} {noun} — treat this cautiously."
    return result
