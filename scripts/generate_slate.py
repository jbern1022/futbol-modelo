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
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold

from models.dixon_coles import DixonColes, derive_markets, knockout_extension
from predictions.generator import (Inference, build_slate, log_degenerate_candidates,
                                   persist_slate, TARGET_BAND)

# Emission threshold for CORNERS/SOT candidates in build_props_inferences()
# below -- distinct from generator.TARGET_BAND, which ranks/selects among
# already-emitted candidates across every market. This one decides whether
# a raw model line is confident enough to become a candidate at all; it's
# deliberately wider than TARGET_BAND to leave build_slate() something to
# rank. Named here (rather than left as bare literals) so the two bands
# can't silently drift apart without it being visible in a diff.
PROPS_OVER_BAND = (0.55, 0.80)
PROPS_UNDER_BAND = (0.20, 0.45)

lgb: Any
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

PROPS_MARKETS: dict[str, dict[str, Any]] = {
    "CORNERS": {"target_col": "corners", "lines": [3.5, 4.5, 5.5, 6.5],
                "for_col": "corners_for_r5", "against_col": "corners_against_r5"},
    "SOT": {"target_col": "shots_on_target", "lines": [2.5, 3.5, 4.5, 5.5],
            "for_col": "sot_for_r5", "against_col": "sot_against_r5"},
}
PROPS_LEAGUES = {"EPL", "SERIE_A", "MLS"}


def find_fixture(cur, league: str, home: str, away: str) -> tuple | None:
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


def fit_dixon_coles(cur, league: str) -> tuple[DixonColes, dict]:
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
    reg = 8.0 if len(df) < 200 else 0.0
    xi = 0.0005 if len(df) < 200 else 0.0015
    dc = DixonColes(xi=xi).fit(df, reg=reg)
    meta = {
        "xi": xi, "reg": reg, "n_matches": len(df),
        "training_window": (f"{df['date'].min().date()}..{df['date'].max().date()}"
                            if len(df) else None),
    }
    return dc, meta


def current_form(cur, team_id: int, kickoff: datetime) -> dict:
    kickoff_aware = kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=timezone.utc)
    cur.execute(
        """SELECT tms.corners, tms.shots, tms.shots_on_target, tms.xg,
                  o.corners AS corners_c, o.shots AS shots_c,
                  o.shots_on_target AS sot_c, o.xg AS xg_c, m.kickoff_utc
           FROM futbol.team_match_stats tms
           JOIN futbol.matches m ON m.match_id = tms.match_id
           JOIN futbol.team_match_stats o
             ON o.match_id = tms.match_id AND o.team_id <> tms.team_id
           WHERE tms.team_id = %s AND m.status = 'final'
             AND m.kickoff_utc BETWEEN %s AND %s
           ORDER BY m.kickoff_utc DESC LIMIT 5""",
        (team_id, kickoff_aware - timedelta(days=90), kickoff_aware))
    rows = cur.fetchall()
    # Fewer than 3 games inside the 90-day window means either preseason
    # or too far removed from a squad rebuild to call it "current form" --
    # return empty (candidate generation skips this team/market) rather
    # than silently averaging stale games from months ago.
    if len(rows) < 3:
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


def fit_props_model(cur, market: str) -> tuple[Any, list[str], dict, dict]:
    spec = PROPS_MARKETS[market]
    features = ["corners_for_r5", "corners_against_r5", "shots_for_r5",
               "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"] \
               if market == "CORNERS" else \
               ["sot_for_r5", "sot_against_r5", "shots_for_r5",
               "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"]
    # n_prior >= 5: a team with 1-2 prior matches gets a "rolling 5" average
    # that's really just those 1-2 games, fed to the model as if it were a
    # full window. Extends ADR-007's small-sample honesty threshold (used
    # elsewhere for UI disclaimers) down into training data itself.
    cur.execute(
        f"""SELECT {', '.join('f.'+c for c in features)}, tms.{spec['target_col']} AS y
            FROM futbol.team_match_features f
            JOIN futbol.matches m ON m.match_id = f.match_id
            JOIN futbol.seasons s ON s.season_id = m.season_id
            JOIN futbol.leagues l ON l.league_id = s.league_id
            JOIN futbol.team_match_stats tms
              ON tms.match_id = f.match_id AND tms.team_id = f.team_id
            WHERE l.code = ANY(%s) AND tms.{spec['target_col']} IS NOT NULL
              AND f.n_prior >= 5""",
        (list(PROPS_LEAGUES),))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=features + ["y"])
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna()
    df["is_home"] = df["is_home"].astype(int)

    # Out-of-fold isotonic calibration (5-fold), matching the standalone
    # validation in scripts/train_props_corners.py that confirmed
    # overconfidence at the high-probability tail. The live pipeline
    # trains fresh every run (no saved model file), so calibration must
    # also be refit fresh every run using the same OOF approach -- a
    # calibrator fit on in-sample predictions would just relearn the
    # model's own overconfidence rather than correct it.
    calibrators = {}
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof_mu = np.zeros(len(df))
    for train_idx, val_idx in kf.split(df):
        fold_model = lgb.LGBMRegressor(objective="poisson", n_estimators=300,
                                       learning_rate=0.03, num_leaves=20,
                                       min_child_samples=30, subsample=0.8,
                                       colsample_bytree=0.8, verbose=-1)
        fold_model.fit(df[features].iloc[train_idx], df["y"].iloc[train_idx])
        oof_mu[val_idx] = np.maximum(
            fold_model.predict(df[features].iloc[val_idx]), 0.05)

    for line in spec["lines"]:
        raw_p = 1 - poisson.cdf(np.floor(line), oof_mu)
        actual = (df["y"].values > line).astype(int)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        iso.fit(raw_p, actual)
        calibrators[line] = iso

    hyperparams = {"objective": "poisson", "n_estimators": 300, "learning_rate": 0.03,
                   "num_leaves": 20, "min_child_samples": 30, "subsample": 0.8,
                   "colsample_bytree": 0.8}
    meta = {
        "features": features, "hyperparams": hyperparams,
        "n_rows": len(df), "oof_mae": round(float(np.mean(np.abs(oof_mu - df["y"].values))), 4),
    }

    model = lgb.LGBMRegressor(verbose=-1, **hyperparams)
    model.fit(df[features], df["y"])
    return model, features, calibrators, meta


def build_props_inferences(model: Any, features: dict, is_home: bool, team_id: int,
                           market: str, team_name: str, calibrators: dict) -> list[Inference]:
    spec = PROPS_MARKETS[market]
    row = pd.DataFrame([{**features, "is_home": int(is_home)}])
    feat_cols = ["corners_for_r5", "corners_against_r5", "shots_for_r5",
                "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"] \
                if market == "CORNERS" else \
                ["sot_for_r5", "sot_against_r5", "shots_for_r5",
                "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"]
    mu = max(model.predict(row[feat_cols])[0], 0.05)
    out = []
    market_label = "Corners" if market == "CORNERS" else "Shots on Target"
    for line in spec["lines"]:
        raw_p = float(1 - poisson.cdf(np.floor(line), mu))
        calibrator = calibrators.get(line)
        p = float(calibrator.predict([raw_p])[0]) if calibrator is not None else raw_p
        if PROPS_OVER_BAND[0] <= p <= PROPS_OVER_BAND[1]:
            side, stated_p = "over", p
        elif PROPS_UNDER_BAND[0] <= p <= PROPS_UNDER_BAND[1]:
            # Low P(over) is a genuine high-confidence P(under) claim, not a
            # weak "over" one -- flip it so the ledger actually gets
            # under-side calibration support instead of never emitting it.
            side, stated_p = "under", 1 - p
        else:
            continue
        out.append(Inference(
            market=market, statement=f"{team_name} — {market_label} {side} {line}",
            line=line, side=side, probability=round(stated_p, 5),
            subject_team_id=team_id, context=features))
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


def likely_goalkeeper(cur, team_id: int) -> tuple[int, str] | None:
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


def fit_player_goals_model(cur) -> tuple[Any, list[str]]:
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


def fit_player_saves_model(cur) -> tuple[Any, list[str]]:
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


def build_player_goal_inference(model: Any, features_list: list[str], form: dict,
                                player_id: int, player_name: str) -> Inference | None:
    row = pd.DataFrame([form])
    mu = max(model.predict(row[features_list])[0], 0.02)
    p = float(1 - poisson.cdf(0, mu))
    if not (0.15 <= p <= 0.60):
        return None
    return Inference(market="PLAYER_GOALS", statement=f"{player_name} to score",
                     line=0.5, side="over", probability=round(p, 5),
                     subject_player_id=player_id, context=form)


def build_player_saves_inference(model: Any, features_list: list[str], form: dict,
                                 player_id: int, player_name: str,
                                 line: float = 3.5) -> Inference | None:
    row = pd.DataFrame([form])
    mu = max(model.predict(row[features_list])[0], 0.1)
    p = float(1 - poisson.cdf(np.floor(line), mu))
    if not (0.20 <= p <= 0.80):
        return None
    return Inference(market="PLAYER_SAVES", statement=f"{player_name} over {line} saves",
                     line=line, side="over", probability=round(p, 5),
                     subject_player_id=player_id, context=form)


def generate_for_fixture(conn, cur, league: str, home: str, away: str,
                         match_id: int, kickoff: datetime, home_id: int, away_id: int,
                         verbose: bool = True) -> int | None:
    now = datetime.now(timezone.utc)
    kickoff_aware = kickoff if kickoff.tzinfo else kickoff.replace(tzinfo=timezone.utc)
    if now >= kickoff_aware:
        if verbose:
            print(f"  SKIP {home} vs {away}: kickoff already passed")
        return None

    # A fixture gets one slate, ever -- persist_slate's ON CONFLICT dedupes
    # by (match_id, model_version_id, ...), which does NOT catch a re-run
    # under a different model_version_id (e.g. after a retrain), so a
    # manual re-run against an already-slated match would otherwise double
    # the fixture's predictions. auto_slate.py's own query already excludes
    # already-slated matches, but that guard lived only there -- this
    # check belongs here so it protects every caller, not just the cron
    # entry point. (Real incident: match_id 4456 got slated twice, three
    # weeks apart under two different model_version_id rows, producing 14
    # duplicate prediction pairs that are now permanently unfixable since
    # both copies were already graded before this was caught.)
    cur.execute(
        "SELECT 1 FROM futbol.predictions WHERE match_id = %s LIMIT 1",
        (match_id,))
    if cur.fetchone():
        if verbose:
            print(f"  SKIP {home} vs {away}: already has a slate")
        return None

    dc, dc_meta = fit_dixon_coles(cur, league)
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

    props_meta = {}
    if league in PROPS_LEAGUES and lgb is not None:
        home_form = current_form(cur, home_id, kickoff)
        away_form = current_form(cur, away_id, kickoff)
        if home_form and away_form:
            for market in PROPS_MARKETS:
                model, _, calibrators, meta = fit_props_model(cur, market)
                props_meta[market] = meta
                candidates += build_props_inferences(model, home_form, True, home_id, market, home, calibrators)
                candidates += build_props_inferences(model, away_form, False, away_id, market, away, calibrators)

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

    candidates = log_degenerate_candidates(cur, match_id, candidates, verbose)
    slate = build_slate(candidates, band=TARGET_BAND, size=20)

    # Stable per league+code-version, NOT per fixture -- every fixture in
    # this league on this code version dedupes into the same row via
    # ON CONFLICT, so the registry actually means something (was
    # previously f"{home}_v_{away}_{date}", which never conflicted and
    # minted one throwaway row per fixture forever).
    cur.execute(
        """INSERT INTO futbol.model_versions
             (model_name, version_tag, training_window, params, train_metrics)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (model_name, version_tag) DO UPDATE
             SET training_window = EXCLUDED.training_window,
                 params = EXCLUDED.params,
                 train_metrics = EXCLUDED.train_metrics
           RETURNING model_version_id""",
        (f"slate_generator_{league.lower()}", "v1",
         dc_meta["training_window"],
         json.dumps({"dixon_coles": {"xi": dc_meta["xi"], "reg": dc_meta["reg"]},
                     "props": {m: meta["hyperparams"] | {"features": meta["features"]}
                               for m, meta in props_meta.items()}}),
         json.dumps({"dixon_coles_n_matches": dc_meta["n_matches"],
                     "props_oof_mae": {m: meta["oof_mae"] for m, meta in props_meta.items()},
                     "props_n_rows": {m: meta["n_rows"] for m, meta in props_meta.items()}})))
    mvid = cur.fetchone()[0]

    n = persist_slate(conn, match_id, mvid, slate)
    if verbose:
        print(f"  OK {home} vs {away}: {n} predictions written "
              f"(match_id={match_id}, model_version_id={mvid})")
    return n


def main() -> None:
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
