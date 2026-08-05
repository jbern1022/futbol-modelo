"""
Quick look: fit Dixon-Coles on whatever real match data is currently in the
DB (no holdout — there's only one season loaded so far, so this is a
first-look at current form, not a rigorous backtest). Once the full
5-season backfill lands, use scripts/train_dixon_coles.py instead for the
real walk-forward backtest.

    python scripts/quick_look.py --league SERIE_A
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import psycopg2

from models.dixon_coles import DixonColes, derive_markets

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

Q = """
SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
       m.home_goals AS hg, m.away_goals AS ag
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons se USING (season_id)
JOIN futbol.leagues l USING (league_id)
WHERE l.code = %s AND m.status = 'final'
ORDER BY m.kickoff_utc;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    df["date"] = pd.to_datetime(df["date"])
    conn.close()

    print(f"\nFitting Dixon-Coles on {len(df)} real {args.league} matches...\n")
    model = DixonColes(xi=0.0018).fit(df)

    n = len(model.teams)
    idx = {t: i for i, t in enumerate(model.teams)}
    atk, dfn = model.params[:n], model.params[n:2 * n]
    ratings = sorted(
        [(t, atk[idx[t]], dfn[idx[t]]) for t in model.teams],
        key=lambda x: -x[1]
    )
    print(f"{'Team':<22} {'Attack':>8} {'Defence':>8}")
    print("-" * 40)
    for team, a, d in ratings:
        print(f"{team:<22} {a:>8.3f} {d:>8.3f}")

    print("\n--- Example predictions (current form, no holdout) ---\n")
    top3 = [t for t, _, _ in ratings[:3]]
    bottom3 = [t for t, _, _ in ratings[-3:]]
    examples = [(top3[0], bottom3[0]), (top3[0], top3[1]), (bottom3[-1], bottom3[-2])]
    for home, away in examples:
        pred = model.predict(home, away)
        mk = derive_markets(pred)
        print(f"{home} vs {away}:")
        print(f"  Home {mk['home_win']:.1%}  Draw {mk['draw']:.1%}  Away {mk['away_win']:.1%}")
        print(f"  Over 2.5 goals: {mk['over_2.5']:.1%}   BTTS: {mk['btts_yes']:.1%}")
        top_score = mk['top_scorelines'][0]
        print(f"  Most likely score: {top_score[0][0]}-{top_score[0][1]} ({top_score[1]:.1%})\n")


if __name__ == "__main__":
    main()
