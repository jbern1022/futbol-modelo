"""
Grading engine.

Two jobs:
  1. Nightly: grade every ungraded prediction whose match is final.
     Writes to prediction_grades (append-only). Never touches predictions.
  2. Season-end: full scorecard — hit rates, Brier, log loss, calibration
     curve per market/league/confidence bucket — rendered as a report and
     exposed to Grafana via the SQL views in schema.sql.

Grading semantics:
  - Over/under lines use half-lines so pushes are impossible where set;
    integer lines that land exactly grade 'void'.
  - 1X2 grades against 90-minute result (standard convention).
  - Postponed/abandoned matches -> 'void'.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

GRADER_VERSION = "grader-1.0"


# ---------- per-prediction grading ----------

def grade_prediction(pred: dict, match: dict, stats: dict) -> tuple[str, float | None]:
    """
    pred:  row from predictions
    match: row from matches (final)
    stats: dict of observed values keyed by (market, subject) — assembled
           by the caller from team_match_stats / player_match_stats
    Returns (outcome, actual_value).
    """
    market, side, line = pred["market"], pred["side"], pred["line"]

    if match["status"] != "final":
        return "void", None

    if market == "1X2":
        hg, ag = match["home_score"], match["away_score"]
        result = "home" if hg > ag else ("away" if ag > hg else "draw")
        return ("hit" if side == result else "miss"), float(hg - ag)

    if market == "BTTS":
        both = match["home_score"] > 0 and match["away_score"] > 0
        want = side == "yes"
        return ("hit" if both == want else "miss"), float(both)

    if market == "TOTAL_GOALS" or market == "TOTAL_POINTS":
        total = match["home_score"] + match["away_score"]
        return _grade_line(total, line, side)

    if market == "MONEYLINE":
        # 2-way, no draw -- NFL/NBA. A tied match dict (shouldn't happen in
        # either real sport; both resolve ties in-game) voids rather than
        # guessing a winner.
        hg, ag = match["home_score"], match["away_score"]
        if hg == ag:
            return "void", float(hg - ag)
        result = "home" if hg > ag else "away"
        return ("hit" if side == result else "miss"), float(hg - ag)

    if market == "SPREAD":
        # side names which team the prediction is about (home/away); line
        # is that team's spread in standard signed convention (negative =
        # favored by that many points, positive = getting that many).
        # "Covers" means the team's signed margin beats its own negated
        # spread -- e.g. side=home, line=-3.5 covers iff (hg-ag) > 3.5.
        # Reduces exactly to _grade_line on the signed margin, which
        # already handles the exact-push case (line lands on an integer).
        hg, ag = match["home_score"], match["away_score"]
        margin = (hg - ag) if side == "home" else (ag - hg)
        return _grade_line(margin, -line, "over")

    # count markets — caller supplies the observed value
    actual = stats.get("actual")
    if actual is None:
        return "void", None
    return _grade_line(actual, line, side)


def _grade_line(actual: float, line: float, side: str) -> tuple[str, float]:
    if actual == line:                       # integer line push
        return "void", float(actual)
    over = actual > line
    hit = (side == "over" and over) or (side == "under" and not over)
    return ("hit" if hit else "miss"), float(actual)


# ---------- nightly job ----------

UNGRADED_SQL = """
SELECT p.prediction_id, p.match_id, p.market, p.side, p.line,
       p.subject_team_id, p.subject_player_id,
       m.status, m.home_score, m.away_score
FROM futbol.predictions p
JOIN futbol.matches m USING (match_id)
LEFT JOIN futbol.prediction_grades g USING (prediction_id)
WHERE g.prediction_id IS NULL
  AND m.status IN ('final', 'postponed', 'abandoned');
"""

def run_nightly(conn, fetch_observed) -> int:
    """
    fetch_observed(pred_row) -> {'actual': value} for count markets.
    Supplied by the stats layer so the grader stays market-agnostic.
    """
    graded = 0
    with conn.cursor() as cur:
        cur.execute(UNGRADED_SQL)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for row in rows:
        match = {k: row[k] for k in ("status", "home_score", "away_score")}
        stats = fetch_observed(row) if row["market"] not in ("1X2", "BTTS", "TOTAL_GOALS") else {}
        outcome, actual = grade_prediction(row, match, stats)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO futbol.prediction_grades
                   (prediction_id, outcome, actual_value, graded_at, grader_version)
                   VALUES (%s,%s,%s,%s,%s)""",
                (row["prediction_id"], outcome, actual,
                 datetime.now(timezone.utc), GRADER_VERSION),
            )
        graded += 1
    conn.commit()
    return graded


# ---------- season-end scorecard ----------

def season_report(conn, league_code: str, season_label: str) -> dict:
    """Pulls the SQL views and assembles the end-of-season report dict."""
    report = {"league": league_code, "season": season_label,
              "generated_at": datetime.now(timezone.utc).isoformat()}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM futbol.v_season_scorecard WHERE league=%s AND season=%s",
            (league_code, season_label))
        cols = [d[0] for d in cur.description]
        report["by_market"] = [dict(zip(cols, r)) for r in cur.fetchall()]

        cur.execute(
            "SELECT * FROM futbol.v_calibration WHERE league=%s ORDER BY market, prob_bucket",
            (league_code,))
        cols = [d[0] for d in cur.description]
        report["calibration_curve"] = [dict(zip(cols, r)) for r in cur.fetchall()]

    # headline: is the 60-75% band actually landing 60-75%?
    band = [b for b in report["calibration_curve"]
            if 0.60 <= float(b["avg_stated_prob"]) <= 0.75]
    if band:
        n = sum(int(b["n"]) for b in band)
        realized = sum(float(b["realized_rate"]) * int(b["n"]) for b in band) / n
        stated = sum(float(b["avg_stated_prob"]) * int(b["n"]) for b in band) / n
        report["headline_band"] = {
            "n": n, "stated": round(stated, 4), "realized": round(realized, 4),
            "gap": round(realized - stated, 4),
        }
    return report


if __name__ == "__main__":
    print(json.dumps({"grader": GRADER_VERSION, "status": "module ok"}))
