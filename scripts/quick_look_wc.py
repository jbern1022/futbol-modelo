"""
Quick look: fit Dixon-Coles on World Cup 2026 results so far, show team
ratings, and predict the four confirmed quarterfinals with knockout-stage
advancement probabilities (draws aren't possible — ET/pens kick in).

Small-sample caveat: most teams have only played 2-4 games, so these
ratings are noisy compared to a full club season. Treat as directional.

    python scripts/quick_look_wc.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import psycopg2

from models.dixon_coles import DixonColes, derive_markets, knockout_extension

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

Q = """
SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
       m.home_goals AS hg, m.away_goals AS ag
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons se USING (season_id)
JOIN futbol.leagues l USING (league_id)
WHERE l.code = 'WC' AND m.status = 'final'
ORDER BY m.kickoff_utc;
"""

QUARTERFINALS = [
    ("France", "Morocco"),
    ("Spain", "Belgium"),
    ("Norway", "England"),
    ("Argentina", "Switzerland"),
]


def main():
    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=())
    df["date"] = pd.to_datetime(df["date"])
    conn.close()

    print(f"\nFitting Dixon-Coles on {len(df)} real World Cup 2026 matches...")
    print("(small-sample caveat: most teams have played only 2-4 games)\n")
    model = DixonColes(xi=0.0005).fit(df, reg=8.0)

    n = len(model.teams)
    idx = {t: i for i, t in enumerate(model.teams)}
    atk, dfn = model.params[:n], model.params[n:2 * n]
    ratings = sorted(
        [(t, atk[idx[t]], dfn[idx[t]]) for t in model.teams],
        key=lambda x: -x[1]
    )
    print(f"{'Team':<22} {'Attack':>8} {'Defence':>8}")
    print("-" * 40)
    for team, a, d in ratings[:15]:
        print(f"{team:<22} {a:>8.3f} {d:>8.3f}")
    print(f"... ({len(ratings)} teams total)\n")

    print("--- Quarterfinal predictions (knockout: no draw possible) ---\n")
    for home, away in QUARTERFINALS:
        if home not in model.teams or away not in model.teams:
            print(f"{home} vs {away}: skipped (insufficient data)\n")
            continue
        pred = model.predict(home, away)
        mk = derive_markets(pred)
        adv = knockout_extension(mk)
        print(f"{home} vs {away}:")
        print(f"  90-min:  Home {mk['home_win']:.1%}  Draw {mk['draw']:.1%}  Away {mk['away_win']:.1%}")
        print(f"  ADVANCES: {home} {adv['advance_home']:.1%}  vs  {away} {adv['advance_away']:.1%}")
        print(f"  Over 2.5 goals: {mk['over_2.5']:.1%}   BTTS: {mk['btts_yes']:.1%}\n")


if __name__ == "__main__":
    main()
