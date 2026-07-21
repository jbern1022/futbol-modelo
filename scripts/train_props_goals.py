"""
Phase F prototype: goals-scored props model.

Predicts each team's expected goals in a match from rolling xG features
(the only features populated so far — FBref-sourced ones like corners
and possession are still blocked). Uses a legitimate time-based
train/test split (chronological, not random) since we only have one
season: train on the first 80% of matches, test on the last 20%. This
is a real evaluation, just a modest one — a proper walk-forward
backtest needs the multi-season backfill from Phase C.

    python scripts/train_props_goals.py --league SERIE_A
    python scripts/train_props_goals.py --league EPL
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

Q = """
SELECT
    f.match_id, f.team_id, f.is_home, f.kickoff_utc,
    f.xg_for_r5, f.xg_against_r5, f.rest_days,
    th.name AS team_name,
    CASE WHEN f.is_home THEN m.home_goals ELSE m.away_goals END AS goals_scored,
    CASE WHEN f.is_home THEN ta.name ELSE th2.name END AS opponent
FROM futbol.team_match_features f
JOIN futbol.matches m ON m.match_id = f.match_id
JOIN futbol.teams th ON th.team_id = f.team_id
JOIN futbol.teams th2 ON th2.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = %s AND f.xg_for_r5 IS NOT NULL
ORDER BY f.kickoff_utc;
"""

FEATURES = ["xg_for_r5", "xg_against_r5", "rest_days", "is_home"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    args = ap.parse_args()

    if lgb is None:
        raise SystemExit("lightgbm not installed — pip install lightgbm --break-system-packages")

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    conn.close()

    df["is_home"] = df["is_home"].astype(int)
    df = df.dropna(subset=FEATURES + ["goals_scored"])
    print(f"\n{len(df)} team-match rows with complete rolling features "
          f"(first match per team excluded — no prior history yet)\n")

    split = int(len(df) * 0.8)
    train, test = df.iloc[:split], df.iloc[split:]
    print(f"Train: {len(train)} rows (earlier matches)")
    print(f"Test:  {len(test)} rows (most recent matches, held out)\n")

    X_train, y_train = train[FEATURES], train["goals_scored"]
    X_test, y_test = test[FEATURES], test["goals_scored"]

    model = lgb.LGBMRegressor(
        objective="poisson", n_estimators=150, learning_rate=0.05,
        num_leaves=15, min_child_samples=15, verbose=-1,
    )
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    pred = np.clip(pred, 0.05, None)

    baseline_mu = y_train.mean()

    def poisson_log_loss(y_true, mu):
        mu = np.clip(mu, 1e-6, None)
        return -np.mean(poisson.logpmf(y_true.astype(int), mu))

    model_ll = poisson_log_loss(y_test, pred)
    baseline_ll = poisson_log_loss(y_test, np.full(len(y_test), baseline_mu))
    mae_model = np.mean(np.abs(y_test.values - pred))
    mae_baseline = np.mean(np.abs(y_test.values - baseline_mu))

    print("--- Held-out test set evaluation ---")
    print(f"Naive baseline (league avg {baseline_mu:.2f} goals/match):")
    print(f"  MAE: {mae_baseline:.3f}   Poisson log-loss: {baseline_ll:.3f}")
    print(f"Model:")
    print(f"  MAE: {mae_model:.3f}   Poisson log-loss: {model_ll:.3f}")
    verdict = "BEATS baseline" if model_ll < baseline_ll else "does NOT beat baseline"
    print(f"  -> Model {verdict}\n")

    print("--- Sample predictions (held-out matches) ---\n")
    test = test.copy()
    test["predicted_goals"] = pred
    for _, row in test.head(8).iterrows():
        venue = "home" if row["is_home"] else "away"
        print(f"{row['team_name']:<20} vs {row['opponent']:<20} ({venue}): "
              f"predicted {row['predicted_goals']:.2f}, actual {int(row['goals_scored'])}")


if __name__ == "__main__":
    main()
