"""
Phase F, real attempt: corners props model with proper multi-season
holdout (train on 2021-22 through 2024-25, test on 2025-26 — the same
season Dixon-Coles was backtested against). Uses real corner data from
API-Football across all 5 seasons, not the single-season snapshot from
the earlier prototype.

    python scripts/train_props_corners.py --league SERIE_A
    python scripts/train_props_corners.py --league EPL
    python scripts/train_props_corners.py --league BOTH   (cross-league)
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
    f.corners_for_r5, f.corners_against_r5,
    f.shots_for_r5, f.shots_against_r5,
    f.xg_for_r5, f.xg_against_r5, f.rest_days,
    s.label AS season, l.code AS league,
    th.name AS team_name,
    CASE WHEN f.is_home THEN ta.name ELSE th2.name END AS opponent,
    tms.corners AS corners_actual
FROM futbol.team_match_features f
JOIN futbol.matches m ON m.match_id = f.match_id
JOIN futbol.teams th ON th.team_id = f.team_id
JOIN futbol.teams th2 ON th2.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.team_match_stats tms ON tms.match_id = f.match_id AND tms.team_id = f.team_id
WHERE l.code = ANY(%s) AND tms.corners IS NOT NULL
ORDER BY f.kickoff_utc;
"""

FEATURES = ["corners_for_r5", "corners_against_r5", "shots_for_r5",
           "shots_against_r5", "xg_for_r5", "xg_against_r5", "rest_days", "is_home"]
LINES = [3.5, 4.5, 5.5, 6.5]
HOLDOUT_SEASON = "2025-26"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["SERIE_A", "EPL", "BOTH"])
    args = ap.parse_args()

    if lgb is None:
        raise SystemExit("lightgbm not installed")

    leagues = ["SERIE_A", "EPL"] if args.league == "BOTH" else [args.league]

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(leagues,))
    conn.close()

    df["is_home"] = df["is_home"].astype(int)
    df = df.dropna(subset=FEATURES + ["corners_actual"])
    print(f"\n{len(df)} team-match rows with complete features across "
          f"{df['season'].nunique()} seasons\n")

    train = df[df.season != HOLDOUT_SEASON]
    test = df[df.season == HOLDOUT_SEASON]
    print(f"Train: {len(train)} rows (seasons {sorted(train.season.unique())})")
    print(f"Test:  {len(test)} rows (held-out season {HOLDOUT_SEASON})\n")

    X_train, y_train = train[FEATURES], train["corners_actual"]
    X_test, y_test = test[FEATURES], test["corners_actual"]

    model = lgb.LGBMRegressor(
        objective="poisson", n_estimators=300, learning_rate=0.03,
        num_leaves=20, min_child_samples=30, subsample=0.8,
        colsample_bytree=0.8, verbose=-1,
    )
    model.fit(X_train, y_train)
    pred_mu = np.clip(model.predict(X_test), 0.05, None)

    baseline_mu = y_train.mean()

    def poisson_log_loss(y_true, mu):
        mu = np.clip(mu, 1e-6, None)
        return -np.mean(poisson.logpmf(y_true.astype(int), mu))

    model_ll = poisson_log_loss(y_test, pred_mu)
    baseline_ll = poisson_log_loss(y_test, np.full(len(y_test), baseline_mu))
    mae_model = np.mean(np.abs(y_test.values - pred_mu))
    mae_baseline = np.mean(np.abs(y_test.values - baseline_mu))

    print("--- Held-out season evaluation (Poisson log-loss, lower=better) ---")
    print(f"Naive baseline (train-set avg {baseline_mu:.2f} corners/match):")
    print(f"  MAE: {mae_baseline:.3f}   Log-loss: {baseline_ll:.3f}")
    print(f"Model:")
    print(f"  MAE: {mae_model:.3f}   Log-loss: {model_ll:.3f}")
    verdict = "BEATS baseline" if model_ll < baseline_ll else "does NOT beat baseline"
    improvement = (baseline_ll - model_ll) / baseline_ll * 100
    print(f"  -> Model {verdict} ({improvement:+.1f}% log-loss)\n")

    print("--- Calibration by line (stated probability vs realized rate) ---\n")
    for line in LINES:
        raw_p = 1 - poisson.cdf(np.floor(line), pred_mu)
        actual_over = (y_test.values > line).astype(int)
        buckets = pd.qcut(raw_p, q=4, duplicates="drop")
        calib = pd.DataFrame({"bucket": buckets, "stated": raw_p, "actual": actual_over})
        summary = calib.groupby("bucket", observed=True).agg(
            n=("actual", "size"), stated=("stated", "mean"), realized=("actual", "mean"))
        print(f"Over {line} corners:")
        for _, row in summary.iterrows():
            print(f"  stated {row['stated']:.1%} -> realized {row['realized']:.1%} "
                  f"(n={int(row['n'])})")
        print()

    print("--- Sample predictions (held-out season) ---\n")
    test = test.copy()
    test["predicted_corners"] = pred_mu
    for _, row in test.head(6).iterrows():
        venue = "home" if row["is_home"] else "away"
        print(f"{row['team_name']:<20} vs {row['opponent']:<20} ({venue}, {row['league']}): "
              f"predicted {row['predicted_corners']:.2f}, actual {int(row['corners_actual'])}")


if __name__ == "__main__":
    main()
