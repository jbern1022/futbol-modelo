"""
Backfill futbol.home_advantage_history: fits Dixon-Coles separately per
(league, season) using ONLY that season's finished matches, and persists
the resulting home-advantage term (gamma) permanently. See migration
0024 for why this needed its own table -- model_versions has nowhere a
per-season series could actually accumulate.

Deliberately a different fit than the live model: generate_slate.py's
fit_dixon_coles() trains on all available history for the best live
prediction. This script isolates each season on purpose, because the
point here is to see gamma drift season over season, not to reproduce
the live model's output.

    python scripts/backfill_home_advantage.py [--league MLS]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import psycopg2

from models.dixon_coles import DixonColes

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# A season with too few finished matches doesn't have enough signal for a
# stable gamma fit -- the live model's own low-data fallback (reg=8.0
# below ~200 matches) kicks in far below a realistic single-season count
# anyway, so this is a lower floor specific to isolating one season at a
# time rather than borrowing the live threshold.
MIN_MATCHES = 60


def seasons_for_league(cur, league: str) -> list[str]:
    cur.execute(
        """SELECT DISTINCT s.label
           FROM futbol.seasons s
           JOIN futbol.leagues l ON l.league_id = s.league_id
           JOIN futbol.matches m ON m.season_id = s.season_id
           WHERE l.code = %s AND m.status = 'final'
           ORDER BY 1""", (league,))
    return [row[0] for row in cur.fetchall()]


def fit_season(cur, league: str, season: str) -> tuple[float, int] | None:
    cur.execute(
        """SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
                  m.home_score AS hg, m.away_score AS ag
           FROM futbol.matches m
           JOIN futbol.teams th ON th.team_id = m.home_team_id
           JOIN futbol.teams ta ON ta.team_id = m.away_team_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = %s AND s.label = %s AND m.status = 'final'
           ORDER BY m.kickoff_utc""", (league, season))
    rows = cur.fetchall()
    if len(rows) < MIN_MATCHES:
        return None
    df = pd.DataFrame(rows, columns=["date", "home", "away", "hg", "ag"])
    df["date"] = pd.to_datetime(df["date"])
    # xi=0 -- a single season is already the time window; no need to
    # additionally decay within it the way the live cross-season model does.
    dc = DixonColes(xi=0.0).fit(df, reg=2.0)
    gamma = float(dc.params[2 * len(dc.teams)])
    return gamma, len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", default=None, help="Restrict to one league code")
    args = parser.parse_args()

    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            # Dixon-Coles is a low-score bivariate-Poisson model (module
            # docstring) -- fitting it against NBA/NFL scorelines isn't
            # just out of scope, it's numerically broken (confirmed: real
            # overflow warnings from exp() on 100+-point NBA games during
            # early testing of this script). Soccer only.
            cur.execute("SELECT code FROM futbol.leagues WHERE sport = 'soccer' ORDER BY 1")
            leagues = [args.league] if args.league else [row[0] for row in cur.fetchall()]

            written = 0
            for league in leagues:
                for season in seasons_for_league(cur, league):
                    result = fit_season(cur, league, season)
                    if result is None:
                        print(f"  SKIP {league} {season}: fewer than {MIN_MATCHES} finished matches")
                        continue
                    gamma, n = result
                    cur.execute(
                        """INSERT INTO futbol.home_advantage_history
                             (league, season, gamma, n_matches, fitted_at)
                           VALUES (%s, %s, %s, %s, now())
                           ON CONFLICT (league, season) DO UPDATE
                             SET gamma = EXCLUDED.gamma, n_matches = EXCLUDED.n_matches,
                                 fitted_at = EXCLUDED.fitted_at""",
                        (league, season, gamma, n))
                    written += 1
                    print(f"  {league} {season}: gamma={gamma:.4f} (n={n})")
        conn.commit()
        print(f"\n{written} (league, season) rows written.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
