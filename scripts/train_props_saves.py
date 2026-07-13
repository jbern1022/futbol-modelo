"""
Goalkeeper saves props model — same rigor as the goals model (season
holdout), plus the goalkeeper's own team's shots_against_r5 (shots
conceded), since save opportunities are driven by opponent shot
volume, not the keeper's own recent form.

    python scripts/train_props_saves.py
"""
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
HOLDOUT_SEASON = "2026"

Q = """
SELECT
    pf.p_saves_r5, pf.p_minutes_r5,
    tf.shots_against_r5, tf.corners_against_r5,
    p.full_name, th.name AS team_name, s.label AS season,
    CASE WHEN pf.team_id = m.home_team_id THEN ta.name ELSE th2.name END AS opponent,
    pms.saves AS saves_actual
FROM futbol.player_match_features pf
JOIN futbol.matches m ON m.match_id = pf.match_id
JOIN futbol.players p ON p.player_id = pf.player_id
JOIN futbol.teams th ON th.team_id = pf.team_id
JOIN futbol.teams th2 ON th2.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.player_match_stats pms ON pms.match_id = pf.match_id AND pms.player_id = pf.player_id
JOIN futbol.team_match_features tf ON tf.match_id = pf.match_id AND tf.team_id = pf.team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = 'MLS' AND p.position = 'G' AND pms.minutes >= 45
  AND pms.saves IS NOT NULL
ORDER BY m.kickoff_utc;
"""

FEATURES = ["p_saves_r5", "p_minutes_r5", "shots_against_r5", "corners_against_r5"]
LINES = [2.5, 3.5, 4.5]


def main():
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn)
    conn.close()

    df[FEATURES] = df[FEATURES].apply(pd.to_numeric, errors="coerce")
    df = df.dropna(subset=FEATURES + ["saves_actual"])
    print(f"\n{len(df)} goalkeeper-match rows across {df['season'].nunique()} seasons\n")

    if len(df) < 200:
        print("Too few goalkeeper rows for a meaningful holdout yet. Exiting.")
        return

    train = df[df.season != HOLDOUT_SEASON]
    test = df[df.season == HOLDOUT_SEASON]
    print(f"Train: {len(train)} rows (seasons {sorted(train.season.unique())})")
    print(f"Test:  {len(test)} rows (held-out season {HOLDOUT_SEASON})\n")

    X_train, y_train = train[FEATURES], train["saves_actual"]
    X_test, y_test = test[FEATURES], test["saves_actual"]

    model = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.03,
                              num_leaves=20, min_child_samples=25, verbose=-1)
    model.fit(X_train, y_train)
    pred_mu = np.clip(model.predict(X_test), 0.1, None)
    baseline_mu = y_train.mean()

    def poisson_log_loss(y_true, mu):
        mu = np.clip(mu, 1e-6, None)
        return -np.mean(poisson.logpmf(y_true.astype(int), mu))

    model_ll = poisson_log_loss(y_test, pred_mu)
    baseline_ll = poisson_log_loss(y_test, np.full(len(y_test), baseline_mu))
    improvement = (baseline_ll - model_ll) / baseline_ll * 100

    print("--- Held-out season evaluation (Poisson log-loss, lower=better) ---")
    print(f"Baseline ({baseline_mu:.2f} saves/appearance): log-loss {baseline_ll:.3f}")
    print(f"Model:                                 log-loss {model_ll:.3f}")
    verdict = "BEATS baseline" if model_ll < baseline_ll else "does NOT beat baseline"
    print(f"-> {verdict} ({improvement:+.1f}%)\n")

    print("--- Calibration by line ---\n")
    for line in LINES:
        raw_p = 1 - poisson.cdf(np.floor(line), pred_mu)
        actual = (y_test.values > line).astype(int)
        print(f"Over {line} saves: avg stated {raw_p.mean():.1%}, "
              f"realized {actual.mean():.1%} (n={len(actual)})")

    print("\n--- Sample predictions (held-out season) ---\n")
    test = test.copy()
    test["predicted_saves"] = pred_mu
    for _, row in test.head(8).iterrows():
        print(f"{row['full_name']:<22} ({row['team_name']:<18} vs {row['opponent']:<18}): "
              f"predicted {row['predicted_saves']:.2f}, actual {int(row['saves_actual'])}")


if __name__ == "__main__":
    main()
