"""
Compute bootstrap confidence intervals on every team's Dixon-Coles
attack/defence rating (Todoist: "Uncertainty intervals on team
attack/defence ratings"; src/models/team_ratings.py has the
statistical core). Full recompute every run (truncate + insert),
matching this project's "retrain from scratch" pattern.

Deliberately the SAME fit as the live model (xi/reg thresholds from
generate_slate.py's fit_dixon_coles, all available history, time-decay
weighted) -- unlike scripts/backfill_home_advantage.py, which
isolates one season at a time on purpose. The point here is "how
uncertain is the rating actually driving today's live predictions,"
not a season-by-season series.

    python scripts/compute_team_ratings.py [--n-boot 100]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# models.team_ratings imports dixon_coles, now its own standalone package
# (packages/dixon-coles) -- see that package's README for why.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import pandas as pd
import psycopg2

from models.team_ratings import bootstrap_team_ratings
from ops.json_logging import configure_json_logging
from ops.pipeline_run import track_run

log = configure_json_logging("compute_team_ratings")

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Same set fit_dixon_coles() would use live for these leagues -- team
# ratings for a league with too little data to fit reliably aren't
# worth computing CIs for either.
LEAGUES = ("MLS", "EPL", "SERIE_A", "LA_LIGA")


def matches_for_league(cur, league: str) -> pd.DataFrame:
    cur.execute(
        """SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
                  m.home_score AS hg, m.away_score AS ag
           FROM futbol.matches m
           JOIN futbol.teams th ON th.team_id = m.home_team_id
           JOIN futbol.teams ta ON ta.team_id = m.away_team_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = %s AND m.status = 'final'
           ORDER BY m.kickoff_utc""", (league,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["date", "home", "away", "hg", "ag"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-boot", type=int, default=100)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    with track_run("compute_team_ratings") as set_rows_written:
        all_rows = []
        with conn.cursor() as cur:
            for league in LEAGUES:
                df = matches_for_league(cur, league)
                # Same low-data fallback thresholds as the live model
                # (generate_slate.py's fit_dixon_coles) -- a league
                # this sparse gets a wider ridge penalty and slower
                # decay there too, so the CIs should reflect the same
                # regularized fit predictions are actually made from.
                reg = 8.0 if len(df) < 200 else 0.0
                xi = 0.0005 if len(df) < 200 else 0.0015
                if len(df) < 60:
                    log.info("skipping league, too little data",
                             extra={"league": league, "n_matches": len(df)})
                    continue
                log.info("bootstrapping league",
                         extra={"league": league, "n_matches": len(df), "n_boot": args.n_boot})
                ratings = bootstrap_team_ratings(df, xi=xi, reg=reg, n_boot=args.n_boot)
                for team, r in ratings.items():
                    all_rows.append({
                        "league": league, "team": team, "n_matches": len(df), **r,
                    })
                log.info("league done", extra={"league": league, "n_teams": len(ratings)})

        with conn.cursor() as cur:
            cur.execute("TRUNCATE futbol.team_ratings")
            for r in all_rows:
                cur.execute(
                    """INSERT INTO futbol.team_ratings
                         (league, team, atk, atk_ci_low, atk_ci_high,
                          dfn, dfn_ci_low, dfn_ci_high, n_boot_samples, n_matches)
                       VALUES (%(league)s, %(team)s, %(atk)s, %(atk_ci_low)s, %(atk_ci_high)s,
                               %(dfn)s, %(dfn_ci_low)s, %(dfn_ci_high)s,
                               %(n_boot_samples)s, %(n_matches)s)""",
                    r)
        conn.commit()
        set_rows_written(len(all_rows))
        log.info("compute_team_ratings done", extra={"n_ratings_written": len(all_rows)})
    conn.close()


if __name__ == "__main__":
    main()
