"""
futbol-modelo portal API — read-only FastAPI backend serving fixtures,
slates, and the season scorecard from Postgres. Uses the futbol_ro role
(SELECT-only), never the main futbol user — this API can't write to the
ledger even in the event of a bug.

Run locally:
    uvicorn api.main:app --reload --port 8000

Endpoints (versioned under /v1 -- /health, /, and the docs/openapi
routes are deliberately unversioned infra/meta endpoints):
    GET /v1/fixtures?league=MLS&status=scheduled&days=21
    GET /v1/fixtures/{match_id}/slate
    GET /v1/scorecard?league=MLS
    GET /v1/calibration?league=MLS
    GET /v1/teams?league=MLS
    POST /v1/ask  {"market": "CORNERS", "league": "MLS"}
    POST /v1/ask/team-form  {"team": "Seattle Sounders", "stat": "corners", "games": 10}
    POST /v1/ask/head-to-head  {"team_a": "Seattle Sounders", "team_b": "LA Galaxy"}
    POST /v1/ask/match-take  {"match_id": 4456}
"""
import csv
import io
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.judgment_filter import contains_unsupported_judgment as _contains_unsupported_judgment

RO_DSN = os.environ.get(
    "FUTBOL_RO_DSN",
    "host=futbol-db dbname=futbol user=futbol_ro password=CHANGE_ME",
)
OLLAMA_URL = os.environ.get("FUTBOL_OLLAMA_URL", "http://192.168.4.48:11434")
OLLAMA_MODEL = "llama3.2:latest"

# Simple in-memory sliding-window rate limit for the public Petey
# endpoints. Appropriately scoped for a single-pod portfolio site --
# not meant to survive a pod restart or scale across replicas, just to
# stop casual abuse of a public, LLM-backed endpoint.
RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
_request_log: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    # Real client IP travels through Cloudflare -> NPM -> k3s as
    # X-Forwarded-For; the raw connection IP would just be NPM's pod.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Scorecard/calibration change at most once a night (grading runs once,
# slates once); a short in-process TTL cache avoids hitting Postgres on
# every page view without risking genuinely stale data.
CACHE_TTL_SECONDS = 300
_response_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, compute):
    now = time.time()
    cached = _response_cache.get(key)
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    value = compute()
    _response_cache[key] = (now, value)
    return value


def _enforce_rate_limit(request: Request):
    ip = _client_ip(request)
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    recent = [t for t in _request_log[ip] if t > window_start]
    if len(recent) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many requests -- please wait a moment before asking Petey again.")
    recent.append(now)
    _request_log[ip] = recent
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


DB_POOL = psycopg2.pool.ThreadedConnectionPool(
    1, 10, RO_DSN, cursor_factory=psycopg2.extras.RealDictCursor
)


def get_conn():
    conn = DB_POOL.getconn()
    conn.autocommit = True
    return conn


def put_conn(conn):
    DB_POOL.putconn(conn)


class RootResponse(BaseModel):
    service: str
    status: str
    endpoints: list[str]


class HealthResponse(BaseModel):
    status: str


class PipelineJob(BaseModel):
    job_name: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    rows_written: Optional[int] = None


class PipelineStatusResponse(BaseModel):
    jobs: list[PipelineJob]


class FixtureSummary(BaseModel):
    match_id: int
    league: str
    season: str
    home: str
    away: str
    kickoff_utc: datetime
    status: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    n_predictions: int
    headline_statement: Optional[str] = None
    headline_probability: Optional[float] = None


class FixturesResponse(BaseModel):
    count: int
    fixtures: list[FixtureSummary]


class Fixture(BaseModel):
    match_id: int
    league: str
    home: str
    away: str
    kickoff_utc: datetime
    status: str


class SlatePrediction(BaseModel):
    prediction_id: int
    market: str
    statement: str
    side: Optional[str] = None
    line: Optional[float] = None
    probability: float
    locked_at: datetime
    context: Optional[dict] = None
    subject_team: Optional[str] = None
    subject_player: Optional[str] = None
    outcome: Optional[str] = None
    actual_value: Optional[float] = None


class SlateResponse(BaseModel):
    fixture: Fixture
    predictions: list[SlatePrediction]


class PredictionDetail(BaseModel):
    prediction_id: int
    market: str
    statement: str
    side: Optional[str] = None
    line: Optional[float] = None
    probability: float
    locked_at: datetime
    created_at: datetime
    context: Optional[dict] = None
    subject_team: Optional[str] = None
    subject_player: Optional[str] = None
    outcome: Optional[str] = None
    actual_value: Optional[float] = None
    graded_at: Optional[datetime] = None
    model_name: str
    version_tag: str
    trained_at: datetime
    match_id: int
    league: str
    home: str
    away: str
    kickoff_utc: datetime
    status: str


class Miss(BaseModel):
    prediction_id: int
    market: str
    statement: str
    side: Optional[str] = None
    probability: float
    locked_at: datetime
    actual_value: Optional[float] = None
    subject_team: Optional[str] = None
    subject_player: Optional[str] = None
    match_id: int
    league: str
    home: str
    away: str
    kickoff_utc: datetime


class MissesResponse(BaseModel):
    count: int
    misses: list[Miss]


class PredictionLogRow(BaseModel):
    prediction_id: int
    market: str
    statement: str
    side: Optional[str] = None
    probability: float
    outcome: str
    actual_value: Optional[float] = None
    subject_team: Optional[str] = None
    subject_player: Optional[str] = None
    match_id: int
    league: str
    season: str
    home: str
    away: str
    kickoff_utc: datetime


class PredictionLogResponse(BaseModel):
    count: int
    predictions: list[PredictionLogRow]


class ScorecardRow(BaseModel):
    league: str
    season: str
    market: str
    n_predictions: int
    hit_rate: float
    avg_confidence: float
    brier: float
    log_loss: float


class ScorecardResponse(BaseModel):
    count: int
    scorecard: list[ScorecardRow]


class CalibrationRow(BaseModel):
    market: str
    league: str
    prob_bucket: int
    avg_stated_prob: float
    realized_rate: float
    n: int
    side: str


class CalibrationResponse(BaseModel):
    count: int
    calibration: list[CalibrationRow]


class AskResponse(BaseModel):
    answer: str
    n_predictions: int
    hit_rate: Optional[float] = None
    avg_confidence: Optional[float] = None
    small_sample: bool
    disclaimer: Optional[str] = None


class TeamsResponse(BaseModel):
    teams: list[str]


class TeamFormResponse(BaseModel):
    answer: str
    n_games: int
    team: Optional[str] = None
    stat: Optional[str] = None
    average: Optional[float] = None
    small_sample: bool
    disclaimer: Optional[str] = None


@app.get("/docs-public", include_in_schema=False)
def public_docs():
    """Swagger UI is on by default at /docs, but that's never been
    publicly reachable -- the public domain's /api/* paths only exist
    where web/app/api/*/route.ts proxies them, and FastAPI's own /docs
    HTML hardcodes openapi_url="/openapi.json" (resolves wrong once
    proxied under /api/docs). This is the same page, generated with an
    openapi_url that resolves correctly through that proxy instead."""
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="futbol-modelo API")


@app.get("/", response_model=RootResponse)
def root():
    return {"service": "futbol-modelo API", "status": "ok",
            "endpoints": ["/v1/fixtures", "/v1/fixtures/{match_id}/slate",
                         "/v1/scorecard", "/v1/calibration", "/v1/teams", "/v1/ask",
                         "/v1/ask/team-form", "/v1/ask/head-to-head",
                         "/v1/ask/match-take", "/v1/pipeline-status"]}


@app.get("/health", response_model=HealthResponse)
def health():
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            put_conn(conn)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"database unreachable: {e}")
    return {"status": "ok"}


@app.get("/v1/pipeline-status", response_model=PipelineStatusResponse)
def pipeline_status():
    """Latest run of each tracked job (auto_slate:*, auto_grade,
    nightly_refresh:*) -- backs the "last updated" freshness indicator."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (job_name)
                       job_name, status, started_at, finished_at, rows_written
                FROM futbol.pipeline_runs
                ORDER BY job_name, started_at DESC
            """)
            rows = cur.fetchall()
    finally:
        put_conn(conn)
    return {"jobs": rows}


@app.get("/v1/fixtures", response_model=FixturesResponse)
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
                       m.home_score, m.away_score,
                       (SELECT COUNT(*) FROM futbol.predictions p
                        WHERE p.match_id = m.match_id) AS n_predictions,
                       headline.statement AS headline_statement,
                       headline.probability AS headline_probability
                FROM futbol.matches m
                JOIN futbol.teams th ON th.team_id = m.home_team_id
                JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                JOIN futbol.seasons s ON s.season_id = m.season_id
                JOIN futbol.leagues l ON l.league_id = s.league_id
                LEFT JOIN LATERAL (
                    SELECT p.statement, p.probability
                    FROM futbol.predictions p
                    WHERE p.match_id = m.match_id AND p.market = '1X2'
                    ORDER BY p.probability DESC
                    LIMIT 1
                ) headline ON true
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
        put_conn(conn)


@app.get("/v1/fixtures/{match_id}/slate", response_model=SlateResponse)
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
                          p.line, p.probability, p.locked_at, p.context,
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
        put_conn(conn)


@app.get("/v1/predictions/{prediction_id}", response_model=PredictionDetail)
def get_prediction(prediction_id: int):
    """Single-prediction permalink data -- statement, model version, lock
    timestamp, grade, and the fixture it belongs to, so every prediction
    is individually citable."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.prediction_id, p.market, p.statement, p.side,
                          p.line, p.probability, p.locked_at, p.created_at,
                          p.context,
                          tt.name AS subject_team,
                          pl.full_name AS subject_player,
                          g.outcome, g.actual_value, g.graded_at,
                          mv.model_name, mv.version_tag, mv.trained_at,
                          m.match_id, l.code AS league, th.name AS home,
                          ta.name AS away, m.kickoff_utc, m.status
                   FROM futbol.predictions p
                   JOIN futbol.matches m ON m.match_id = p.match_id
                   JOIN futbol.teams th ON th.team_id = m.home_team_id
                   JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                   JOIN futbol.seasons s ON s.season_id = m.season_id
                   JOIN futbol.leagues l ON l.league_id = s.league_id
                   JOIN futbol.model_versions mv ON mv.model_version_id = p.model_version_id
                   LEFT JOIN futbol.teams tt ON tt.team_id = p.subject_team_id
                   LEFT JOIN futbol.players pl ON pl.player_id = p.subject_player_id
                   LEFT JOIN futbol.prediction_grades g
                     ON g.prediction_id = p.prediction_id
                   WHERE p.prediction_id = %s""", (prediction_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Prediction not found")
        return row
    finally:
        put_conn(conn)


@app.get("/v1/predictions", response_model=PredictionLogResponse)
def list_predictions(
    league: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None, description="hit or miss"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated, filterable log of every individually graded prediction
    -- the "honest, unfiltered record" Track Record's copy promises but,
    until now, never actually rendered a single row of. Built on
    v_graded_predictions so a fixture that somehow got slated twice
    can't double-count here either, matching /scorecard and
    /calibration exactly."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT gp.prediction_id, gp.market, p.statement, gp.side,
                       gp.probability, gp.outcome, g.actual_value,
                       tt.name AS subject_team, pl.full_name AS subject_player,
                       gp.match_id, gp.league, gp.season,
                       th.name AS home, ta.name AS away, m.kickoff_utc
                FROM futbol.v_graded_predictions gp
                JOIN futbol.predictions p ON p.prediction_id = gp.prediction_id
                JOIN futbol.prediction_grades g ON g.prediction_id = gp.prediction_id
                JOIN futbol.matches m ON m.match_id = gp.match_id
                JOIN futbol.teams th ON th.team_id = m.home_team_id
                JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                LEFT JOIN futbol.teams tt ON tt.team_id = p.subject_team_id
                LEFT JOIN futbol.players pl ON pl.player_id = p.subject_player_id
                WHERE 1=1
            """
            params: list = []
            if league:
                query += " AND gp.league = %s"
                params.append(league)
            if season:
                query += " AND gp.season = %s"
                params.append(season)
            if market:
                query += " AND gp.market = %s"
                params.append(market)
            if outcome:
                query += " AND gp.outcome = %s"
                params.append(outcome)

            cur.execute(f"SELECT COUNT(*) AS count FROM ({query}) sub", params)
            count = cur.fetchone()["count"]

            query += " ORDER BY m.kickoff_utc DESC LIMIT %s OFFSET %s"
            cur.execute(query, params + [limit, offset])
            rows = cur.fetchall()
        return {"count": count, "predictions": rows}
    finally:
        put_conn(conn)


@app.get("/v1/misses", response_model=MissesResponse)
def biggest_misses(league: Optional[str] = Query(None), limit: int = Query(20, le=100)):
    """Highest-confidence predictions that missed, most confident first --
    the honesty-first counterpart to only ever showing hits."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT p.prediction_id, p.market, p.statement, p.side,
                       p.probability, p.locked_at, g.actual_value,
                       tt.name AS subject_team, pl.full_name AS subject_player,
                       m.match_id, l.code AS league, th.name AS home,
                       ta.name AS away, m.kickoff_utc
                FROM futbol.predictions p
                JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
                JOIN futbol.matches m ON m.match_id = p.match_id
                JOIN futbol.teams th ON th.team_id = m.home_team_id
                JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                JOIN futbol.seasons s ON s.season_id = m.season_id
                JOIN futbol.leagues l ON l.league_id = s.league_id
                LEFT JOIN futbol.teams tt ON tt.team_id = p.subject_team_id
                LEFT JOIN futbol.players pl ON pl.player_id = p.subject_player_id
                WHERE g.outcome = 'miss'
            """
            params: list = []
            if league:
                query += " AND l.code = %s"
                params.append(league)
            query += " ORDER BY p.probability DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, params)
            rows = cur.fetchall()
        return {"count": len(rows), "misses": rows}
    finally:
        put_conn(conn)


@app.get("/v1/export/predictions.csv")
def export_predictions_csv(league: Optional[str] = Query(None)):
    """Every graded prediction we've ever made, with grades. Anyone can
    download this and recompute the track record themselves."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT l.code AS league, s.label AS season, th.name AS home,
                       ta.name AS away, m.kickoff_utc, p.market, p.statement,
                       p.side, p.line, p.probability, p.locked_at,
                       tt.name AS subject_team, pl.full_name AS subject_player,
                       g.outcome, g.actual_value, g.graded_at
                FROM futbol.predictions p
                JOIN futbol.matches m ON m.match_id = p.match_id
                JOIN futbol.teams th ON th.team_id = m.home_team_id
                JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                JOIN futbol.seasons s ON s.season_id = m.season_id
                JOIN futbol.leagues l ON l.league_id = s.league_id
                LEFT JOIN futbol.teams tt ON tt.team_id = p.subject_team_id
                LEFT JOIN futbol.players pl ON pl.player_id = p.subject_player_id
                JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
                WHERE g.outcome <> 'void'
            """
            params = []
            if league:
                query += " AND l.code = %s"
                params.append(league)
            query += " ORDER BY m.kickoff_utc, p.prediction_id"
            cur.execute(query, params)
            rows = cur.fetchall()
    finally:
        put_conn(conn)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["league", "season", "home", "away", "kickoff_utc", "market",
                     "statement", "side", "line", "probability", "locked_at",
                     "subject_team", "subject_player", "outcome", "actual_value",
                     "graded_at"])
    for r in rows:
        writer.writerow([r[k] for k in (
            "league", "season", "home", "away", "kickoff_utc", "market",
            "statement", "side", "line", "probability", "locked_at",
            "subject_team", "subject_player", "outcome", "actual_value",
            "graded_at")])
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=futbol-modelo-predictions.csv"})


@app.get("/v1/scorecard", response_model=ScorecardResponse)
def scorecard(league: Optional[str] = Query(None)):
    def compute():
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
            put_conn(conn)
    return _cached(f"scorecard:{league}", compute)


@app.get("/v1/calibration", response_model=CalibrationResponse)
def calibration(league: Optional[str] = Query(None)):
    def compute():
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                query = "SELECT * FROM futbol.v_calibration WHERE n >= 3"
                params = []
                if league:
                    query += " AND league = %s"
                    params.append(league)
                query += " ORDER BY league, market, side, avg_stated_prob"
                cur.execute(query, params)
                rows = cur.fetchall()
            return {"count": len(rows), "calibration": rows}
        finally:
            put_conn(conn)
    return _cached(f"calibration:{league}", compute)


class AskRequest(BaseModel):
    market: str
    league: str


@app.post("/v1/ask", response_model=AskResponse)
def ask_petey(req: AskRequest, request: Request):
    """
    Petey v1 — first real slice. Per ADR-002/ADR-008: Ollama never sees
    raw rows or writes any query. This endpoint looks up one real,
    pre-computed aggregate and asks Ollama only to phrase that exact
    number as a sentence. Per ADR-007, flags small samples (n < 5).
    Per ADR-005, hard 20s timeout with a graceful, still-honest fallback.
    """
    _enforce_rate_limit(request)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM futbol.v_season_scorecard
                   WHERE market = %s AND league = %s""",
                (req.market, req.league))
            row = cur.fetchone()
    finally:
        put_conn(conn)

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
        if not answer or _contains_unsupported_judgment(answer):
            raise ValueError("empty or unsupported-judgment response")
    except Exception:
        # Broad catch is deliberate here: Ollama is an external, unreliable
        # service (homelab hardware, not a guaranteed API), and ADR-005
        # requires graceful behavior under ANY failure mode — network,
        # malformed response, timeout, or anything else — never a raw
        # 500 or a hang. The real number is still returned either way.
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


@app.get("/v1/teams", response_model=TeamsResponse)
def list_teams(league: Optional[str] = Query(None)):
    """Team names for the frontend's searchable select (ADR-004) —
    real, known values only, no free-text team entry anywhere."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if league:
                cur.execute(
                    """SELECT DISTINCT t.name FROM futbol.teams t
                       JOIN futbol.matches m
                         ON t.team_id IN (m.home_team_id, m.away_team_id)
                       JOIN futbol.seasons s ON s.season_id = m.season_id
                       JOIN futbol.leagues l ON l.league_id = s.league_id
                       WHERE l.code = %s ORDER BY t.name""", (league,))
            else:
                cur.execute("SELECT name FROM futbol.teams ORDER BY name")
            rows = cur.fetchall()
        return {"teams": [r["name"] for r in rows]}
    finally:
        put_conn(conn)


TEAM_FORM_STATS = {
    "corners": "Corners",
    "shots_on_target": "Shots on Target",
    "shots": "Shots",
    "fouls": "Fouls",
    "yellows": "Yellow Cards",
}

class TeamFormRequest(BaseModel):
    team: str
    stat: str
    games: int = 10


@app.post("/v1/ask/team-form", response_model=TeamFormResponse)
def ask_team_form(req: TeamFormRequest, request: Request):
    """
    Team recent-form question. Per ADR-006, backward-looking questions
    use a row limit (last N games), not a date window. This is a
    genuinely different question shape than /ask — real descriptive
    stats from team_match_stats, not prediction accuracy. Same safety
    pattern throughout: `stat` is validated against a fixed allowlist
    BEFORE it ever reaches SQL (never raw user input in the query), and
    Ollama only ever sees the final computed average, never raw rows
    (ADR-002/003/008).
    """
    _enforce_rate_limit(request)
    if req.stat not in TEAM_FORM_STATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stat '{req.stat}'. Valid options: "
                   f"{list(TEAM_FORM_STATS.keys())}")
    games = max(1, min(req.games, 20))  # sane hard bounds, per ADR-004's spirit

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # req.stat is validated against TEAM_FORM_STATS above — this
            # is a lookup into a fixed, known-safe column allowlist, not
            # raw user input reaching SQL.
            cur.execute(
                f"""SELECT tms.{req.stat} AS val
                    FROM futbol.team_match_stats tms
                    JOIN futbol.matches m ON m.match_id = tms.match_id
                    JOIN futbol.teams t ON t.team_id = tms.team_id
                    WHERE t.name = %s AND m.status = 'final'
                      AND tms.{req.stat} IS NOT NULL
                    ORDER BY m.kickoff_utc DESC LIMIT %s""",
                (req.team, games))
            rows = cur.fetchall()
    finally:
        put_conn(conn)

    stat_label = TEAM_FORM_STATS[req.stat]

    if not rows:
        return {
            "answer": f"I don't have recent {stat_label} data for {req.team}.",
            "n_games": 0,
            "small_sample": True,
        }

    vals = [float(r["val"]) for r in rows]
    avg = sum(vals) / len(vals)
    n_games = len(vals)

    summary = (
        f"Team: {req.team}, Stat: {stat_label}, "
        f"Games analyzed: {n_games}, Average: {avg:.1f} per game."
    )
    prompt = (
        "You are Petey, a straightforward sports-analytics assistant. "
        "Turn the following stat summary into ONE short, plain-English "
        "sentence describing this team's recent form. State the number "
        "neutrally — do NOT characterize it as good, bad, high, low, a "
        "struggle, or impressive, since no comparison or baseline is "
        "provided. Do not add any numbers, teams, or facts not present "
        "in the summary below. Do not speculate about future matches.\n\n"
        + summary
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        answer = resp.json().get("response", "").strip()
        if not answer or _contains_unsupported_judgment(answer):
            raise ValueError("empty or unsupported-judgment response")
    except Exception:
        answer = (
            f"{req.team} has averaged {avg:.1f} {stat_label.lower()} per "
            f"game over their last {n_games} matches."
        )

    small_sample = n_games < 5
    result = {
        "answer": answer,
        "team": req.team,
        "stat": stat_label,
        "n_games": n_games,
        "average": round(avg, 2),
        "small_sample": small_sample,
    }
    if small_sample:
        noun = "game" if n_games == 1 else "games"
        result["disclaimer"] = f"Based on only {n_games} {noun} — treat this cautiously."
    return result


class HeadToHeadRequest(BaseModel):
    team_a: str
    team_b: str


class HeadToHeadResponse(BaseModel):
    answer: str
    n_games: int
    team_a: Optional[str] = None
    team_b: Optional[str] = None
    team_a_wins: Optional[int] = None
    team_b_wins: Optional[int] = None
    draws: Optional[int] = None
    small_sample: bool
    disclaimer: Optional[str] = None


@app.post("/v1/ask/head-to-head", response_model=HeadToHeadResponse)
def ask_head_to_head(req: HeadToHeadRequest, request: Request):
    """
    Head-to-head record between two teams -- the 3rd ADR-010 preset.
    All-time meetings, not a rolling window (unlike /ask/team-form):
    head-to-head record is conventionally the full history. Same safety
    pattern as every other Petey endpoint: Ollama only ever sees the
    final computed record, never raw rows (ADR-002/003/008).
    """
    _enforce_rate_limit(request)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT th.name AS home, ta.name AS away,
                          m.home_score, m.away_score
                   FROM futbol.matches m
                   JOIN futbol.teams th ON th.team_id = m.home_team_id
                   JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                   WHERE m.status = 'final'
                     AND ((th.name = %s AND ta.name = %s)
                          OR (th.name = %s AND ta.name = %s))
                   ORDER BY m.kickoff_utc DESC LIMIT 50""",
                (req.team_a, req.team_b, req.team_b, req.team_a))
            rows = cur.fetchall()
    finally:
        put_conn(conn)

    if not rows:
        return {
            "answer": f"I don't have any past meetings between {req.team_a} and {req.team_b}.",
            "n_games": 0,
            "small_sample": True,
        }

    team_a_wins = team_b_wins = draws = 0
    for row in rows:
        home_score, away_score = row["home_score"], row["away_score"]
        if home_score == away_score:
            draws += 1
        elif row["home"] == req.team_a:
            if home_score > away_score:
                team_a_wins += 1
            else:
                team_b_wins += 1
        else:
            if home_score > away_score:
                team_b_wins += 1
            else:
                team_a_wins += 1

    n_games = len(rows)
    summary = (
        f"Team A: {req.team_a}, Team B: {req.team_b}, "
        f"Meetings: {n_games}, {req.team_a} wins: {team_a_wins}, "
        f"{req.team_b} wins: {team_b_wins}, Draws: {draws}."
    )
    prompt = (
        "You are Petey, a straightforward sports-analytics assistant. "
        "Turn the following head-to-head record into ONE short, "
        "plain-English sentence. State the numbers neutrally — do NOT "
        "characterize either team as better, dominant, struggling, or "
        "favored, since this is historical record only, not a "
        "prediction. Do not add any numbers, teams, or facts not "
        "present in the summary below. Do not speculate about future "
        "matches.\n\n" + summary
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        answer = resp.json().get("response", "").strip()
        if not answer or _contains_unsupported_judgment(answer):
            raise ValueError("empty or unsupported-judgment response")
    except Exception:
        answer = (
            f"In their last {n_games} meetings, {req.team_a} won "
            f"{team_a_wins}, {req.team_b} won {team_b_wins}, and "
            f"{draws} ended in a draw."
        )

    small_sample = n_games < 5
    result = {
        "answer": answer,
        "team_a": req.team_a,
        "team_b": req.team_b,
        "n_games": n_games,
        "team_a_wins": team_a_wins,
        "team_b_wins": team_b_wins,
        "draws": draws,
        "small_sample": small_sample,
    }
    if small_sample:
        noun = "meeting" if n_games == 1 else "meetings"
        result["disclaimer"] = f"Based on only {n_games} {noun} — treat this cautiously."
    return result


class MatchTakeRequest(BaseModel):
    match_id: int


class MatchTakeResponse(BaseModel):
    answer: str
    match_id: int
    home: Optional[str] = None
    away: Optional[str] = None
    statement: Optional[str] = None
    probability: Optional[float] = None
    small_sample: bool
    disclaimer: Optional[str] = None


@app.post("/v1/ask/match-take", response_model=MatchTakeResponse)
def ask_match_take(req: MatchTakeRequest, request: Request):
    """
    "What's the model's take on this match?" -- the 4th and final
    ADR-010 preset. Reuses the exact same headline-pick logic as
    /v1/fixtures (highest-probability 1X2 prediction), phrased through
    the same Ollama-sentence pattern as every other Petey endpoint.
    Ollama only ever sees the final computed headline, never raw rows
    (ADR-002/003/008).
    """
    _enforce_rate_limit(request)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.match_id, th.name AS home, ta.name AS away,
                          headline.statement AS statement,
                          headline.probability AS probability
                   FROM futbol.matches m
                   JOIN futbol.teams th ON th.team_id = m.home_team_id
                   JOIN futbol.teams ta ON ta.team_id = m.away_team_id
                   LEFT JOIN LATERAL (
                       SELECT p.statement, p.probability
                       FROM futbol.predictions p
                       WHERE p.match_id = m.match_id AND p.market = '1X2'
                       ORDER BY p.probability DESC
                       LIMIT 1
                   ) headline ON true
                   WHERE m.match_id = %s""", (req.match_id,))
            row = cur.fetchone()
    finally:
        put_conn(conn)

    if not row:
        raise HTTPException(status_code=404, detail="Fixture not found")

    if not row["statement"]:
        return {
            "answer": f"I don't have a slate yet for {row['home']} vs {row['away']}.",
            "match_id": req.match_id,
            "home": row["home"],
            "away": row["away"],
            "small_sample": True,
        }

    probability = float(row["probability"])
    summary = (
        f"Fixture: {row['home']} vs {row['away']}, "
        f"Model's most confident pick: {row['statement']}, "
        f"Stated confidence: {probability * 100:.1f}%."
    )
    prompt = (
        "You are Petey, a straightforward sports-analytics assistant. "
        "Turn the following into ONE short, plain-English sentence "
        "describing the model's most confident prediction for this "
        "match. State the confidence number neutrally — do NOT "
        "characterize it as likely, unlikely, safe, or risky beyond "
        "the number itself. Do not add any numbers, teams, or facts "
        "not present in the summary below. Do not speculate beyond "
        "what's stated.\n\n" + summary
    )

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        answer = resp.json().get("response", "").strip()
        if not answer or _contains_unsupported_judgment(answer):
            raise ValueError("empty or unsupported-judgment response")
    except Exception:
        answer = (
            f"For {row['home']} vs {row['away']}, the model's top pick is "
            f"\"{row['statement']}\" at {probability * 100:.1f}% confidence."
        )

    return {
        "answer": answer,
        "match_id": req.match_id,
        "home": row["home"],
        "away": row["away"],
        "statement": row["statement"],
        "probability": round(probability, 4),
        "small_sample": False,
    }
