"""
The real deal: generate genuine pre-kickoff predictions for an upcoming
match and write them into the immutable futbol.predictions ledger.

Spain vs Belgium (World Cup 2026 quarterfinal) kicks off Friday July 10 —
still in the future as of this run, so this is the project's first
legitimate, non-hypothetical ledger entry.

    python scripts/predict_and_log_wc.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import psycopg2

from models.dixon_coles import DixonColes, derive_markets

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

Q = """
SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
       m.home_score AS hg, m.away_score AS ag
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons se USING (season_id)
JOIN futbol.leagues l USING (league_id)
WHERE l.code = 'WC' AND m.status = 'final'
ORDER BY m.kickoff_utc;
"""

HOME, AWAY = "Norway", "England"


def main():
    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=())
    df["date"] = pd.to_datetime(df["date"])

    print(f"Fitting model on {len(df)} completed World Cup matches...")
    model = DixonColes(xi=0.0005).fit(df, reg=8.0)

    if HOME not in model.teams or AWAY not in model.teams:
        print(f"ERROR: {HOME} or {AWAY} not found in fitted teams.")
        return

    mk = derive_markets(model.predict(HOME, AWAY))
    print(f"\n{HOME} vs {AWAY}:")
    print(f"  Home {mk['home_win']:.1%}  Draw {mk['draw']:.1%}  Away {mk['away_win']:.1%}")
    print(f"  Over 2.5: {mk['over_2.5']:.1%}   BTTS: {mk['btts_yes']:.1%}\n")

    with conn.cursor() as cur:
        cur.execute(
            """SELECT m.match_id, m.kickoff_utc, m.status, th.team_id, ta.team_id
               FROM futbol.matches m
               JOIN futbol.teams th ON th.team_id = m.home_team_id
               JOIN futbol.teams ta ON ta.team_id = m.away_team_id
               WHERE th.name = %s AND ta.name = %s""",
            (HOME, AWAY))
        row = cur.fetchone()
        if not row:
            print(f"ERROR: no match found for {HOME} vs {AWAY} in the DB.")
            return
        match_id, kickoff_utc, status, home_id, away_id = row
        now = datetime.now(timezone.utc)
        print(f"Match status: {status}, kickoff: {kickoff_utc}, now: {now}")
        if now >= kickoff_utc.replace(tzinfo=timezone.utc):
            print("Kickoff has already passed — cannot log a genuine "
                  "pre-kickoff prediction. (This is the trigger working correctly.)")
            return

        cur.execute(
            """INSERT INTO futbol.model_versions
                 (model_name, version_tag, training_window, params, train_metrics)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (model_name, version_tag) DO UPDATE
                 SET train_metrics = EXCLUDED.train_metrics
               RETURNING model_version_id""",
            ("dixon_coles_wc", "quick_look_v1", "wc2026_through_qf",
             '{"xi": 0.0005, "reg": 8.0}',
             f'{{"n_matches": {len(df)}}}'))
        model_version_id = cur.fetchone()[0]

        statements = [
            ("1X2", None, "home", mk["home_win"], f"{HOME} win"),
            ("1X2", None, "draw", mk["draw"], "Draw (90 min)"),
            ("1X2", None, "away", mk["away_win"], f"{AWAY} win"),
            ("TOTAL_GOALS", 2.5, "over", mk["over_2.5"], "Over 2.5 goals"),
            ("BTTS", None, "yes", mk["btts_yes"], "Both teams to score"),
        ]
        inserted = 0
        for market, line, side, prob, label in statements:
            cur.execute(
                """INSERT INTO futbol.predictions
                     (match_id, model_version_id, market, statement, line, side, probability)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (match_id, model_version_id, market, label, line, side, round(prob, 5)))
            inserted += 1
        conn.commit()
        print(f"\n{inserted} predictions written to the immutable ledger "
              f"for match_id={match_id}, model_version_id={model_version_id}.")
        print("This is the project's first genuine, non-hypothetical "
              "pre-kickoff prediction. Grade it after full time.")

    conn.close()


if __name__ == "__main__":
    main()
