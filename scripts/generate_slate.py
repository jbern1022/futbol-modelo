"""
The real Phase G slate generator. Finds an upcoming fixture, fits the
validated models (Dixon-Coles always; corners/SOT/player-props for
leagues with data coverage), computes live "current form", and writes
a genuine pre-kickoff slate through the immutable ledger.

    python scripts/generate_slate.py --league MLS --home Arsenal --away Chelsea

Player-level markets (goals, saves) are MLS-only for now — the only
league with player_match_stats populated so far.
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

from models.dixon_coles import DixonColes, derive_markets
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


def player_goals_form(cur, player_id: int) -> dict:
    cur.execute(
        """SELECT pms.shots, pms.minutes, pms.goals, pms.key_passes
           FROM futbol.player_match_stats pms
           JOIN futbol.matches m ON m.match_id = pms.match_id
           WHERE pms.player_id = %s AND m.status = 'final' AND pms.minutes >= 30
           ORDER BY m.kickoff_utc DESC LIMIT 10""", (player_id,))
    rows = cur.fetchall()
    if len(rows) < 3:
        return {}
    df = pd.DataFrame(rows, columns=["shots", "minutes", "goals", "key_passes"])
    df = df.apply(pd.to_numeric, errors="coerce")
    return {
        "p_shots_r5": df["shots"].head(5).mean(),
        "p_minutes_r5": df["minutes"].head(5).mean(),
        "p_goals_r10": df["goals"].mean(),
        "p_key_passes_r5": df["key_passes"].head(5).mean(),
    }


def top_goal_threats(cur, team_id: int, n: int = 2) -> list:
    cur.execute(
        """SELECT p.player_id, p.full_name, AVG(pms.shots) AS avg_shots
           FROM futbol.player_match_stats pms
           JOIN futbol.matches m ON m.match_id = pms.match_id
           JOIN futbol.players p ON p.player_id = pms.player_id
           WHERE pms.team_id = %s AND m.status = 'final' AND pms.minutes >= 45
             AND p.position IN ('F', 'M') AND m.kickoff_utc > now() - interval '90 days'
           GROUP BY p.player_id, p.full_name
           HAVING COUNT(*) >= 3
           ORDER BY avg_shots DESC LIMIT %s""", (team_id, n))
    return [(pid, name) for pid, name, _ in cur.fetchall()]


def likely_goalkeeper(cur, team_id: int):
    cur.execute(
        """SELECT p.player_id, p.full_name, MAX(m.kickoff_utc) AS last_played
           FROM futbol.player_match_stats pms
           JOIN futbol.matches m ON m.match_id = pms.match_id
           JOIN futbol.players p ON p.player_id = pms.player_id
           WHERE pms.team_id = %s AND m.status = 'final' AND p.position = 'G'
             AND pms.minutes >= 45
           GROUP BY p.player_id, p.full_name
           ORDER BY last_played DESC LIMIT 1""", (team_id,))
    row = cur.fetchone()
    return (row[0], row[1]) if row else None


def fit_player_goals_model(cur):
    features = ["p_shots_r5", "p_minutes_r5", "p_goals_r10", "p_key_passes_r5"]
    cur.execute(
        """SELECT f.p_shots_r5, f.p_minutes_r5, f.p_goals_r10, f.p_key_passes_r5,
                  pms.goals
           FROM futbol.player_match_features f
           JOIN futbol.matches m ON m.match_id = f.match_id
           JOIN futbol.player_match_stats pms
             ON pms.match_id = f.match_id AND pms.player_id = f.player_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = 'MLS' AND pms.minutes >= 45""")
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=features + ["goals"])
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    model = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.03,
                              num_leaves=20, min_child_samples=30, verbose=-1)
    model.fit(df[features], df["goals"])
    return model, features


def fit_player_saves_model(cur):
    features = ["p_saves_r5", "p_minutes_r5", "shots_against_r5", "corners_against_r5"]
    cur.execute(
        """SELECT pf.p_saves_r5, pf.p_minutes_r5, tf.shots_against_r5, tf.corners_against_r5,
                  pms.saves
           FROM futbol.player_match_features pf
           JOIN futbol.matches m ON m.match_id = pf.match_id
           JOIN futbol.players p ON p.player_id = pf.player_id
           JOIN futbol.player_match_stats pms
             ON pms.match_id = pf.match_id AND pms.player_id = pf.player_id
           JOIN futbol.team_match_features tf
             ON tf.match_id = pf.match_id AND tf.team_id = pf.team_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = 'MLS' AND p.position = 'G' AND pms.minutes >= 45
             AND pms.saves IS NOT NULL""")
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=features + ["saves"])
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    model = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.03,
                              num_leaves=20, min_child_samples=25, verbose=-1)
    model.fit(df[features], df["saves"])
    return model, features


def build_player_goal_inference(model, features_list, form, player_id, player_name):
    row = pd.DataFrame([form])
    mu = max(model.predict(row[features_list])[0], 0.02)
    p = float(1 - poisson.cdf(0, mu))
    if not (0.15 <= p <= 0.60):
        return None
    return Inference(market="PLAYER_GOALS", statement=f"{player_name} to score",
                     line=0.5, side="over", probability=round(p, 5),
                     subject_player_id=player_id)


def build_player_saves_inference(model, features_list, form, player_id, player_name, line=3.5):
    row = pd.DataFrame([form])
    mu = max(model.predict(row[features_list])[0], 0.1)
    p = float(1 - poisson.cdf(np.floor(line), mu))
    if not (0.20 <= p <= 0.80):
        return None
    return Inference(market="PLAYER_SAVES", statement=f"{player_name} over {line} saves",
                     line=line, side="over", probability=round(p, 5),
                     subject_player_id=player_id)


def generate_for_fixture(conn, cur, league: str, home: str, away: str,
                         match_id: int, kickoff, home_id: int, away_id: int,
                         verbose: bool = True):
    now = datetime.now(timezone.utc)
    kickoff_aware = kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=timezone.utc)
    if now >= kickoff_aware:
        if verbose:
            print(f"  SKIP {home} vs {away}: kickoff already passed")
        return None

    dc = fit_dixon_coles(cur, league)
    if home not in dc.teams or away not in dc.teams:
        if verbose:
            print(f"  SKIP {home} vs {away}: team(s) not in fitted list")
        return None
    mk = derive_markets(dc.predict(home, away))

    candidates = [
        Inference("1X2", f"{home} win", None, "home", mk["home_win"], home_id),
        Inference("1X2", "Draw (90 min)", None, "draw", mk["draw"]),
        Inference("1X2", f"{away} win", None, "away", mk["away_win"], away_id),
        Inference("TOTAL_GOALS", "Over 2.5 goals", 2.5, "over", mk["over_2.5"]),
        Inference("BTTS", "Both teams to score", None, "yes", mk["btts_yes"]),
    ]

    if league in PROPS_LEAGUES and lgb is not None:
        home_form = current_form(cur, home_id, kickoff)
        away_form = current_form(cur, away_id, kickoff)
        if home_form and away_form:
            for market in PROPS_MARKETS:
                model, _ = fit_props_model(cur, market)
                candidates += build_props_inferences(model, home_form, True, home_id, market)
                candidates += build_props_inferences(model, away_form, False, away_id, market)

        if league == "MLS":
            try:
                goals_model, goals_feats = fit_player_goals_model(cur)
                saves_model, saves_feats = fit_player_saves_model(cur)

                for tid in (home_id, away_id):
                    for pid, pname in top_goal_threats(cur, tid, n=2):
                        form = player_goals_form(cur, pid)
                        if form:
                            inf = build_player_goal_inference(
                                goals_model, goals_feats, form, pid, pname)
                            if inf:
                                candidates.append(inf)

                    gk = likely_goalkeeper(cur, tid)
                    if gk:
                        pid, pname = gk
                        cur.execute(
                            """SELECT pms.saves, pms.minutes
                               FROM futbol.player_match_stats pms
                               JOIN futbol.matches m ON m.match_id = pms.match_id
                               WHERE pms.player_id = %s AND m.status='final'
                                 AND pms.minutes >= 45
                               ORDER BY m.kickoff_utc DESC LIMIT 5""", (pid,))
                        srows = cur.fetchall()
                        if len(srows) >= 3:
                            sdf = pd.DataFrame(srows, columns=["saves", "minutes"])
                            sdf = sdf.apply(pd.to_numeric, errors="coerce")
                            team_form = current_form(cur, tid, kickoff)
                            if team_form:
                                save_form = {
                                    "p_saves_r5": sdf["saves"].mean(),
                                    "p_minutes_r5": sdf["minutes"].mean(),
                                    "shots_against_r5": team_form["shots_against_r5"],
                                    "corners_against_r5": team_form.get("corners_against_r5"),
                                }
                                if save_form["corners_against_r5"] is not None:
                                    inf = build_player_saves_inference(
                                        saves_model, saves_feats, save_form, pid, pname)
                                    if inf:
                                        candidates.append(inf)
            except Exception as e:
                if verbose:
                    print(f"  (player props skipped: {e})")

    slate = build_slate(candidates, size=20)

    cur.execute(
        """INSERT INTO futbol.model_versions
             (model_name, version_tag, training_window, params, train_metrics)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (model_name, version_tag) DO UPDATE
             SET train_metrics = EXCLUDED.train_metrics
           RETURNING model_version_id""",
        (f"slate_generator_{league.lower()}",
         f"{home}_v_{away}_{datetime.now().date()}",
         "live_fit", json.dumps({"league": league}),
         json.dumps({"n_candidates": len(candidates), "n_slate": len(slate)})))
    mvid = cur.fetchone()[0]

    n = persist_slate(conn, match_id, mvid, slate)
    if verbose:
        print(f"  OK {home} vs {away}: {n} predictions written "
              f"(match_id={match_id}, model_version_id={mvid})")
    return n


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
        print(f"Fixture: {args.home} vs {args.away} ({args.league})")
        print(f"Status: {status}, kickoff: {kickoff}")
        generate_for_fixture(conn, cur, args.league, args.home, args.away,
                             match_id, kickoff, home_id, away_id)
    conn.close()


if __name__ == "__main__":
    main()
