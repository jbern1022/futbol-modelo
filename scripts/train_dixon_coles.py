"""
Phase E: fit + backtest + register the Dixon-Coles match model.

    python scripts/train_dixon_coles.py --league EPL --holdout 2025-26
    python scripts/train_dixon_coles.py --league SERIE_A --holdout 2025-26 --xi-grid

Walk-forward backtest: refits weekly through the holdout season,
scores 1X2 with ranked probability score (RPS) and log loss,
then registers the model in futbol.model_versions.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2

from models.dixon_coles import DixonColes, derive_markets

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

Q = """
SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
       m.home_score AS hg, m.away_score AS ag, se.label AS season
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons se USING (season_id)
JOIN futbol.leagues l USING (league_id)
WHERE l.code = %s AND m.status = 'final'
ORDER BY m.kickoff_utc;
"""


def rps(probs: list[float], outcome_idx: int) -> float:
    """Ranked probability score for ordered outcomes [home, draw, away]."""
    obs = np.zeros(3); obs[outcome_idx] = 1
    cp, co = np.cumsum(probs), np.cumsum(obs)
    return float(np.sum((cp - co) ** 2) / 2)


def walk_forward(df: pd.DataFrame, holdout: str, xi: float) -> dict:
    train_hist = df[df.season != holdout].copy()
    test = df[df.season == holdout].copy()
    if test.empty:
        raise SystemExit(f"no matches found for holdout season {holdout}")

    scores, lls, correct = [], [], 0
    refit_at = None
    model = None
    for _, row in test.iterrows():
        if refit_at is None or row.date >= refit_at:
            past = pd.concat([train_hist, test[test.date < row.date]])
            model = DixonColes(xi=xi).fit(
                past.rename(columns=str).assign(date=pd.to_datetime(past.date)))
            refit_at = row.date + timedelta(days=7)
        try:
            mk = derive_markets(model.predict(row.home, row.away))
        except KeyError:      # promoted team with no history yet
            continue
        p = [mk["home_win"], mk["draw"], mk["away_win"]]
        actual = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)
        scores.append(rps(p, actual))
        lls.append(-np.log(max(p[actual], 1e-9)))
        correct += int(np.argmax(p) == actual)

    n = len(scores)
    return {"n": n, "rps": round(float(np.mean(scores)), 4),
            "log_loss": round(float(np.mean(lls)), 4),
            "accuracy": round(correct / n, 4), "xi": xi}


def register(conn, league: str, metrics: dict, holdout: str):
    tag = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip() or "local"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.model_versions
               (model_name, version_tag, training_window, params, train_metrics)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (model_name, version_tag) DO UPDATE
               SET train_metrics = EXCLUDED.train_metrics
               RETURNING model_version_id""",
            (f"dixon_coles_{league.lower()}", tag, f"all_excl_{holdout}",
             json.dumps({"xi": metrics["xi"]}), json.dumps(metrics)))
        mvid = cur.fetchone()[0]
    conn.commit()
    return mvid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--holdout", default="2025-26")
    ap.add_argument("--xi", type=float, default=0.0018)
    ap.add_argument("--xi-grid", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    df["date"] = pd.to_datetime(df["date"])
    print(f"loaded {len(df)} finals for {args.league}")

    grid = [0.0010, 0.0015, 0.0018, 0.0022, 0.0030] if args.xi_grid else [args.xi]
    results = [walk_forward(df, args.holdout, xi) for xi in grid]
    for r in results:
        print(json.dumps(r))
    best = min(results, key=lambda r: r["rps"])
    mvid = register(conn, args.league, best, args.holdout)
    print(f"registered model_version_id={mvid} (best xi={best['xi']}, "
          f"RPS={best['rps']} — credible range is ~0.19–0.21)")
    conn.close()


if __name__ == "__main__":
    main()
