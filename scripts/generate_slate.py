"""
The real Phase G slate generator. Finds an upcoming fixture, fits the
validated models (Dixon-Coles always; corners/SOT only for leagues with
team_match_stats coverage — currently EPL/SERIE_A, not WC), computes
live "current form" for both teams, and writes a genuine pre-kickoff
slate through the immutable ledger.

    python scripts/generate_slate.py --league WC --home France --away Spain
    python scripts/generate_slate.py --league EPL --home Arsenal --away Chelsea
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

from models.dixon_coles import DixonColes, derive_markets, knockout_extension
from predictions.generator import Inference, build_slate, persist_slate

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

PROPS_MARKETS = {
    "CORNERS": {"target_col": "corners", "lines": [3.5, 4.5, 5.5, 6.5],
                "for_col": "corners_for_r5", "against_col": "corners_against_r5"},
    "SOT": {"target_col": "shots_on_target", "lines": [2.5, 3.5, 4.5, 5.5],
            "for_col": "sot_for_r5", "against_col": "sot_against_r5"},
}
PROPS_LEAGUES = {"EPL", "SERIE_A", "MLS"}


def find_fixture(cur, league: str, home: str, away: str):
    cur.execute(
        """SELECT m.match_id, m.kickoff_utc, m.status, m.home_team_id, m.away_team_id
           FROM futbol.matches m
           JOIN futbol.teams th ON th.team_id = m.home_team_id
           JOIN futbol.teams ta ON ta.team_id = m.away_team_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = %s AND th.name = %s AND ta.name = %s
           ORDER BY m.kickoff_utc DESC LIMIT 1""",
        (league, home, away))
    return cur.fetchone()


def fit_dixon_coles(cur, league: str) -> DixonColes:
    cur.execute(
        """SELECT m.kickoff_utc::date AS date, th.name AS home, ta.name AS away,
                  m.home_goals AS hg, m.away_goals AS ag
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
    reg = 8.0 if len(df) < 200 else 0.0
    xi = 0.0005 if len(df) < 200 else 0.0015
    return DixonColes(xi=xi).fit(df, reg=reg)


def current_form(cur, team_id: int, kickoff) -> dict:
    cur.execute(
        """SELECT tms.corners, tms.shots, tms.shots_on_target, tms.xg,
                  o.corners AS corners_c, o.shots AS shots_c,
                  o.shots_on_target AS sot_c, o.xg AS xg_c, m.kickoff_utc
           FROM futbol.team_match_stats tms
           JOIN futbol.matches m ON m.match_id = tms.match_id
           JOIN futbol.team_match_stats o
             ON o.match_id = tms.match_id AND o.team_id <> tms.team_id
           WHERE tms.team_id = %s AND m.status = 'final'
           ORDER BY m.kickoff_utc DESC LIMIT 5""", (team_id,))
    rows = cur.fetchall()
    if not rows:
        return {}
    cols = ["corners", "shots", "sot", "xg", "corners_c", "shots_c", "sot_c", "xg_c", "kickoff"]
    df = pd.DataFrame(rows, columns=cols)
    numeric_cols = [c for c in cols if c != "kickoff"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    last_kickoff = df["kickoff"].max()
    rest_days = (pd.to_datetime(kickoff) - pd.to_datetime(last_kickoff)).days
    return {
        "corners_for_r5": df["corners"].mean(), "corners_against_r5": df["corners_c"].mean(),
        "shots_for_r5": df["shots"].mean(), "shots_against_r5": df["shots_c"].mean(),
        "sot_for_r5": df["sot"].mean(), "sot_against_r5": df["sot_c"].mean(),
        "xg_for_r5": df["xg"].mean(), "xg_against_r5": df["xg_c"].mean(),
        "rest_days": max(rest_days, 1),
    }


def fit_props_model(cur, market: str):
    spec = PROPS_MARKETS[market]
    features = ["corners_for_r5", "corners_against_r5", "shots_for_r5",
               "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"] \
               if market == "CORNERS" else \
               ["sot_for_r5", "sot_against_r5", "shots_for_r5",
               "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"]
    cur.execute(
        f"""SELECT {', '.join('f.'+c for c in features)}, tms.{spec['target_col']} AS y
            FROM futbol.team_match_features f
            JOIN futbol.matches m ON m.match_id = f.match_id
            JOIN futbol.seasons s ON s.season_id = m.season_id
            JOIN futbol.leagues l ON l.league_id = s.league_id
            JOIN futbol.team_match_stats tms
              ON tms.match_id = f.match_id AND tms.team_id = f.team_id
            WHERE l.code = ANY(%s) AND tms.{spec['target_col']} IS NOT NULL""",
        (list(PROPS_LEAGUES),))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=features + ["y"])
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna()
    df["is_home"] = df["is_home"].astype(int)
    model = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.03,
                              num_leaves=20, min_child_samples=30, subsample=0.8,
                              colsample_bytree=0.8, verbose=-1)
    model.fit(df[features], df["y"])
    return model, features


def build_props_inferences(model, features: dict, is_home: bool, team_id: int,
                           market: str) -> list:
    spec = PROPS_MARKETS[market]
    row = pd.DataFrame([{**features, "is_home": int(is_home)}])
    feat_cols = ["corners_for_r5", "corners_against_r5", "shots_for_r5",
                "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"] \
                if market == "CORNERS" else \
                ["sot_for_r5", "sot_against_r5", "shots_for_r5",
                "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"]
    mu = max(model.predict(row[feat_cols])[0], 0.05)
    out = []
    for line in spec["lines"]:
        p = float(1 - poisson.cdf(np.floor(line), mu))
        if not (0.55 <= p <= 0.80 or 0.20 <= p <= 0.45):
            continue
        out.append(Inference(
            market=market, statement=f"{market.title()} over {line}",
            line=line, side="over", probability=round(p, 5),
            subject_team_id=team_id))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        fixture = find_fixture(cur, args.league, args.home, args.away)
        if not fixture:
            print(f"ERROR: no fixture found for {args.home} vs {args.away} in {args.league}")
            return
        match_id, kickoff, status, home_id, away_id = fixture
        now = datetime.now(timezone.utc)
        kickoff_aware = kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=timezone.utc)
        print(f"Fixture: {args.home} vs {args.away} ({args.league})")
        print(f"Status: {status}, kickoff: {kickoff}, now: {now}")
        if now >= kickoff_aware:
            print("Kickoff has already passed — cannot generate a genuine "
                  "pre-kickoff slate. (Trigger will also reject this.)")
            return

        print("\nFitting Dixon-Coles...")
        dc = fit_dixon_coles(cur, args.league)
        if args.home not in dc.teams or args.away not in dc.teams:
            print(f"ERROR: {args.home} or {args.away} not in fitted team list.")
            return
        mk = derive_markets(dc.predict(args.home, args.away))

        candidates = [
            Inference("1X2", f"{args.home} win", None, "home", mk["home_win"], home_id),
            Inference("1X2", "Draw (90 min)", None, "draw", mk["draw"]),
            Inference("1X2", f"{args.away} win", None, "away", mk["away_win"], away_id),
            Inference("TOTAL_GOALS", "Over 2.5 goals", 2.5, "over", mk["over_2.5"]),
            Inference("BTTS", "Both teams to score", None, "yes", mk["btts_yes"]),
        ]

        if args.league in PROPS_LEAGUES and lgb is not None:
            print("Fitting corners + SOT props models (cross-league)...")
            home_form = current_form(cur, home_id, kickoff)
            away_form = current_form(cur, away_id, kickoff)
            if home_form and away_form:
                for market in PROPS_MARKETS:
                    model, _ = fit_props_model(cur, market)
                    candidates += build_props_inferences(model, home_form, True, home_id, market)
                    candidates += build_props_inferences(model, away_form, False, away_id, market)
            else:
                print("  (insufficient match history for props — skipping)")
        else:
            print(f"Skipping props models — {args.league} has no team_match_stats coverage.")

        print(f"\n{len(candidates)} candidate inferences generated:")
        for c in candidates:
            print(f"  {c.statement}: {c.probability:.1%}")

        slate = build_slate(candidates, size=20)

        cur.execute(
            """INSERT INTO futbol.model_versions
                 (model_name, version_tag, training_window, params, train_metrics)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (model_name, version_tag) DO UPDATE
                 SET train_metrics = EXCLUDED.train_metrics
               RETURNING model_version_id""",
            (f"slate_generator_{args.league.lower()}",
             f"{args.home}_v_{args.away}_{datetime.now().date()}",
             "live_fit", json.dumps({"league": args.league}),
             json.dumps({"n_candidates": len(candidates), "n_slate": len(slate)})))
        mvid = cur.fetchone()[0]

        n = persist_slate(conn, match_id, mvid, slate)
        print(f"\n{n} predictions written to the immutable ledger "
              f"(match_id={match_id}, model_version_id={mvid}).")

    conn.close()


if __name__ == "__main__":
    main()
