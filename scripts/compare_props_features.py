"""
Which props feature set should the models actually use?

READ-ONLY. Issues SELECTs and nothing else. Trains models in memory, writes
no artifacts, touches no ledger.

    python scripts/compare_props_features.py --market CORNERS
    python scripts/compare_props_features.py --market all

BACKGROUND
team_match_stats.xg is ~99% populated for EPL/SERIE_A (Understat) and 0%
populated for MLS (API-Football's tier does not supply it). fit_props_model
selects xg_for_r5 / xg_against_r5 then calls dropna(), so every MLS row is
discarded during training. MLS props are therefore produced by a model trained
only on English and Italian football, scored on MLS fixtures where both xG
features arrive as NaN — LightGBM treats NaN as missing, so it never raised.

An earlier run of this script established two things: xG is worth roughly
nothing on European holdout rows (~0.002 logloss on corners, slightly negative
on SOT), and the current model is WORSE THAN A NAIVE BASELINE at predicting
MLS on both markets.

WHAT THIS MEASURES
Four configurations, each scored on both a European and an MLS holdout, so the
cost of any choice is visible on both sides rather than inferred:

  1. EU + xG                  what production does today
  2. EU, no xG                is xG earning its place at all?
  3. ALL, no xG               does pooling MLS in help — or does it degrade
                              Europe, given the model has no way to tell the
                              leagues apart?
  4. ALL, no xG + league_code the proposal: pool everything, but give the model
                              a league indicator so it can learn per-league
                              rates instead of averaging across them

Baselines are per holdout — the mean of that league group's training rows,
i.e. "just predict the league average". A model that cannot beat it has no
business shipping, which is the bar the README already claims for props.

Holdout is the most recent 20% of rows per league by kickoff, since MLS and the
European leagues run on different calendars.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

try:
    import lightgbm as lgb
except ImportError:
    sys.exit("lightgbm is required: pip install lightgbm")

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

BASE_FEATURES = ["shots_for_r5", "shots_against_r5", "rest_days", "is_home"]
XG_FEATURES = ["xg_for_r5", "xg_against_r5"]
EUROPE = ["EPL", "SERIE_A"]

MARKETS = {
    "CORNERS": {"target": "corners",
                "own": ["corners_for_r5", "corners_against_r5"]},
    "SOT": {"target": "shots_on_target",
            "own": ["sot_for_r5", "sot_against_r5"]},
}

LGB_PARAMS = dict(objective="poisson", n_estimators=300, learning_rate=0.03,
                  num_leaves=20, min_child_samples=30, subsample=0.8,
                  colsample_bytree=0.8, verbose=-1)

HOLDOUT_FRACTION = 0.20


def load(conn, market: str) -> pd.DataFrame:
    spec = MARKETS[market]
    cols = spec["own"] + BASE_FEATURES + XG_FEATURES
    select = ", ".join(f"f.{c}" for c in cols)
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT l.code AS league, f.kickoff_utc, {select},
                   tms.{spec['target']} AS y
            FROM futbol.team_match_features f
            JOIN futbol.leagues l ON l.league_id = f.league_id
            JOIN futbol.team_match_stats tms
              ON tms.match_id = f.match_id AND tms.team_id = f.team_id
            WHERE tms.{spec['target']} IS NOT NULL
            ORDER BY f.kickoff_utc
        """)
        rows = cur.fetchall()
        names = [d[0] for d in cur.description]

    df = pd.DataFrame(rows, columns=names)
    for c in cols + ["y"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["is_home"] = df["is_home"].astype(float)
    # Stable integer encoding, fixed before the split so train and test agree.
    codes = {code: i for i, code in enumerate(sorted(df["league"].unique()))}
    df["league_code"] = df["league"].map(codes).astype(int)
    return df


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train, test = [], []
    for _, grp in df.groupby("league", sort=False):
        grp = grp.sort_values("kickoff_utc")
        cut = int(len(grp) * (1 - HOLDOUT_FRACTION))
        train.append(grp.iloc[:cut])
        test.append(grp.iloc[cut:])
    return pd.concat(train), pd.concat(test)


def poisson_logloss(y: np.ndarray, mu: np.ndarray) -> float:
    return float(-poisson.logpmf(y, np.clip(mu, 1e-6, None)).mean())


def fit(train: pd.DataFrame, features: list[str], categorical: bool):
    d = train.dropna(subset=features + ["y"])
    if d.empty:
        return None, 0
    model = lgb.LGBMRegressor(**LGB_PARAMS)
    kwargs = {"categorical_feature": ["league_code"]} if categorical else {}
    model.fit(d[features], d["y"], **kwargs)
    return model, len(d)


def score(model, test: pd.DataFrame, features: list[str],
          baseline_mu: float) -> str:
    """NaN features are deliberately kept — LightGBM treats them as missing,
    which is exactly what production does today."""
    d = test.dropna(subset=["y"])
    if model is None or d.empty:
        return "        —"
    mu = np.clip(model.predict(d[features]), 1e-6, None)
    ll = poisson_logloss(d["y"].to_numpy(), mu)
    delta = poisson_logloss(d["y"].to_numpy(), np.full(len(d), baseline_mu)) - ll
    flag = " " if delta > 0 else "!"
    return f"{ll:.4f} ({delta:+.4f}){flag}"


def run(conn, market: str) -> None:
    spec = MARKETS[market]
    own = spec["own"]
    df = load(conn, market)

    print(f"\n{'=' * 76}\n{market} — target `{spec['target']}`\n{'=' * 76}")
    for league, grp in df.groupby("league"):
        n_xg = int(grp[XG_FEATURES].notna().all(axis=1).sum())
        print(f"  {league:<10} {len(grp):>6} rows, {n_xg:>6} with xG "
              f"({100.0 * n_xg / max(len(grp), 1):.1f}%)")

    train, test = split(df)
    train_eu = train[train["league"].isin(EUROPE)]
    test_eu = test[test["league"].isin(EUROPE)]
    test_mls = test[test["league"] == "MLS"]
    base_eu = train_eu["y"].mean()
    base_mls = train[train["league"] == "MLS"]["y"].mean()

    configs = [
        ("1. EU + xG  (production today)", train_eu, own + BASE_FEATURES + XG_FEATURES, False),
        ("2. EU, no xG",                   train_eu, own + BASE_FEATURES, False),
        ("3. ALL, no xG",                  train,    own + BASE_FEATURES, False),
        ("4. ALL, no xG + league_code",    train,    own + BASE_FEATURES + ["league_code"], True),
    ]

    print(f"\n  {'configuration':<32} {'train':>6}   {'EU holdout':>18}   {'MLS holdout':>18}")
    print(f"  {'-' * 32} {'-' * 6}   {'-' * 18}   {'-' * 18}")
    for label, tr, feats, cat in configs:
        model, n = fit(tr, feats, cat)
        print(f"  {label:<32} {n:>6}   {score(model, test_eu, feats, base_eu):>18}   "
              f"{score(model, test_mls, feats, base_mls):>18}")

    print("\n  logloss (improvement over that holdout's naive baseline). Lower")
    print("  logloss is better; a negative improvement, marked !, means the model")
    print("  is worse than predicting the league average and should not ship.")
    print(f"  EU holdout n={len(test_eu)}, MLS holdout n={len(test_mls)}.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="all", choices=["CORNERS", "SOT", "all"])
    args = ap.parse_args()
    conn = psycopg2.connect(DSN)
    try:
        for m in (list(MARKETS) if args.market == "all" else [args.market]):
            run(conn, m)
    finally:
        conn.close()
    print()


if __name__ == "__main__":
    main()
