"""
Player-minutes projection model -- honest evaluation against the naive
baseline already in production use (p_minutes_r5, a plain rolling-5
average feeding the props models per src/models/props.py's
PLAYER_FEATURES / sql/features.sql).

    python scripts/train_player_minutes_model.py

SCOPE NOTE, read before trusting any "beats the baseline" claim from
this script: the ticket that requested this ("starter/bench, days
rest, blowout risk") assumes lineup/starting-XI data this project does
not ingest at all -- there is no lineups table, no is_starter flag,
nothing. Checked directly (grepped for lineup/starter/starting_xi
across sql/ and src/, nothing soccer-side). "Blowout risk" is also
unbuildable as a pre-match feature -- it's an outcome, not something
knowable before kickoff, without a separate score-projection signal
this script doesn't build either. What IS buildable from data that
actually exists: rolling minutes history (5- and 10-game, mean and
std-dev -- rotation-prone players should show high variance a plain
mean can't see), rest days, and home/away, evaluated the same honest
way as every other model in this repo: does it actually beat a naive
baseline on a real held-out season, not just "does it run."
"""
from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from sklearn.metrics import mean_absolute_error

lgb: Any
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

Q = """
SELECT p.player_id, p.team_id, p.match_id, m.kickoff_utc,
       s.label AS season, l.code AS league,
       (m.home_team_id = p.team_id) AS is_home,
       p.minutes,
       f.rest_days
FROM futbol.player_match_stats p
JOIN futbol.matches m ON m.match_id = p.match_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.team_match_features f
  ON f.match_id = p.match_id AND f.team_id = p.team_id
WHERE l.code = ANY(%s) AND p.minutes IS NOT NULL
ORDER BY p.player_id, m.kickoff_utc;
"""

LEAGUES = ["MLS", "EPL", "SERIE_A", "LA_LIGA"]
# Split by each league's own most recent complete season, same mapping
# used in today's earlier walk-forward backtest work -- MLS uses
# calendar-year season labels, the others split-year.
HOLDOUT_SEASON = {"MLS": "2025", "EPL": "2025-26", "SERIE_A": "2025-26", "LA_LIGA": "2025-26"}

MIN_PRIOR_APPEARANCES = 5  # matches this project's existing n_prior>=5 convention
FEATURES = ["p_minutes_r5", "p_minutes_r10", "p_minutes_std5", "rest_days", "is_home"]


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Leakage-safe rolling features per player, shifted so a match's
    own minutes never contribute to its own features -- same discipline
    as every f.*_r5/r10 column already in sql/features.sql."""
    df = df.sort_values(["player_id", "kickoff_utc"]).copy()
    grp = df.groupby("player_id")["minutes"]
    df["n_prior"] = grp.cumcount()
    df["p_minutes_r5"] = grp.transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df["p_minutes_r10"] = grp.transform(lambda s: s.shift(1).rolling(10, min_periods=1).mean())
    df["p_minutes_std5"] = grp.transform(lambda s: s.shift(1).rolling(5, min_periods=2).std())
    return df


def main():
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(LEAGUES,))
    conn.close()

    df["is_home"] = df["is_home"].astype(int)
    df = add_rolling_features(df)
    df = df[df["n_prior"] >= MIN_PRIOR_APPEARANCES]
    df["p_minutes_std5"] = df["p_minutes_std5"].fillna(0)
    df = df.dropna(subset=FEATURES + ["rest_days"])

    df["is_holdout"] = df.apply(
        lambda r: r["season"] == HOLDOUT_SEASON.get(r["league"]), axis=1)
    train = df[~df["is_holdout"]]
    test = df[df["is_holdout"]]

    print(f"\n{len(df)} player-match rows with {MIN_PRIOR_APPEARANCES}+ prior "
          f"appearances, across {df['league'].nunique()} leagues")
    print(f"Train: {len(train)} rows")
    print(f"Test:  {len(test)} rows (each league's most recent complete season)\n")

    X_train, y_train = train[FEATURES], train["minutes"]
    X_test, y_test = test[FEATURES], test["minutes"]

    model = lgb.LGBMRegressor(
        n_estimators=300, learning_rate=0.03, num_leaves=20,
        min_child_samples=30, subsample=0.8, colsample_bytree=0.8, verbose=-1,
    )
    model.fit(X_train, y_train)
    pred = np.clip(model.predict(X_test), 0, 120)

    baseline_pred = X_test["p_minutes_r5"]  # the feature already in production use

    model_mae = mean_absolute_error(y_test, pred)
    baseline_mae = mean_absolute_error(y_test, baseline_pred)

    print("--- Held-out evaluation: model vs. the naive rolling-5 baseline "
          "already in production ---\n")
    print(f"Naive baseline (p_minutes_r5 alone):  MAE {baseline_mae:.2f} minutes")
    print(f"Model (r5 + r10 + std5 + rest + home): MAE {model_mae:.2f} minutes")
    improvement_pct = (baseline_mae - model_mae) / baseline_mae * 100
    verdict = "BEATS" if model_mae < baseline_mae else "does NOT beat"
    print(f"\n-> Model {verdict} the naive baseline ({improvement_pct:+.1f}% MAE)\n")

    print("--- Feature importance ---\n")
    for feat, imp in sorted(zip(FEATURES, model.feature_importances_), key=lambda x: -x[1]):
        print(f"  {feat:15s} {imp}")

    print("\n--- By league ---\n")
    test = test.copy()
    test["pred"] = pred
    for league in LEAGUES:
        sub = test[test["league"] == league]
        if sub.empty:
            continue
        m_mae = mean_absolute_error(sub["minutes"], sub["pred"])
        b_mae = mean_absolute_error(sub["minutes"], sub["p_minutes_r5"])
        print(f"  {league:10s} n={len(sub):5d}  model={m_mae:.2f}  baseline={b_mae:.2f}  "
              f"({(b_mae - m_mae) / b_mae * 100:+.1f}%)")


if __name__ == "__main__":
    main()
