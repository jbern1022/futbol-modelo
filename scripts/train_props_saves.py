"""
Goalkeeper saves props model — same rigor as the goals model (season
holdout), plus the goalkeeper's own team's shots_against_r5 (shots
conceded), since save opportunities are driven by opponent shot
volume, not the keeper's own recent form.

    python scripts/train_props_saves.py
"""
import os
import sys

from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

lgb: Any
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
    pif.absence_rate_r10,
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
LEFT JOIN futbol.player_injury_features pif
  ON pif.match_id = pf.match_id AND pif.player_id = pf.player_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = 'MLS' AND p.position = 'G' AND pms.minutes >= 45
  AND pms.saves IS NOT NULL
ORDER BY m.kickoff_utc;
"""

FEATURES = ["p_saves_r5", "p_minutes_r5", "shots_against_r5", "corners_against_r5"]
FEATURES_WITH_ABSENCE = FEATURES + ["absence_rate_r10"]
LINES = [2.5, 3.5, 4.5]


def main():
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn)
    conn.close()

    df[FEATURES_WITH_ABSENCE] = df[FEATURES_WITH_ABSENCE].apply(pd.to_numeric, errors="coerce")
    df_base = df.dropna(subset=FEATURES + ["saves_actual"])
    df_absence = df.dropna(subset=FEATURES_WITH_ABSENCE + ["saves_actual"])
    print(f"\n{len(df_base)} goalkeeper-match rows across {df_base['season'].nunique()} seasons\n")

    if len(df_base) < 200:
        print("Too few goalkeeper rows for a meaningful holdout yet. Exiting.")
        return

    def poisson_log_loss(y_true, mu):
        mu = np.clip(mu, 1e-6, None)
        return -np.mean(poisson.logpmf(y_true.astype(int), mu))

    def run(df_variant, features, label):
        train = df_variant[df_variant.season != HOLDOUT_SEASON]
        test = df_variant[df_variant.season == HOLDOUT_SEASON]
        model = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.03,
                                  num_leaves=20, min_child_samples=25, verbose=-1)
        model.fit(train[features], train["saves_actual"])
        pred_mu = np.clip(model.predict(test[features]), 0.1, None)
        baseline_mu = train["saves_actual"].mean()
        model_ll = poisson_log_loss(test["saves_actual"], pred_mu)
        baseline_ll = poisson_log_loss(test["saves_actual"], np.full(len(test), baseline_mu))
        improvement = (baseline_ll - model_ll) / baseline_ll * 100
        print(f"--- {label}: train {len(train)}, test {len(test)} "
              f"(held-out season {HOLDOUT_SEASON}) ---")
        print(f"Naive baseline ({baseline_mu:.2f} saves/appearance): log-loss {baseline_ll:.3f}")
        print(f"Model log-loss: {model_ll:.3f} "
              f"({'BEATS' if model_ll < baseline_ll else 'does NOT beat'} baseline, "
              f"{improvement:+.1f}%)\n")
        return model, pred_mu, test, model_ll

    _, _, _, ll_base = run(df_base, FEATURES, "WITHOUT absence_rate_r10 (current live)")
    _, pred_mu, test, ll_absence = run(
        df_absence, FEATURES_WITH_ABSENCE, "WITH absence_rate_r10 (candidate)")
    delta = (ll_base - ll_absence) / ll_base * 100
    print("--- A/B: absence_rate_r10 vs current live features ---")
    print(f"WITHOUT: log-loss {ll_base:.4f}   WITH: log-loss {ll_absence:.4f}   "
          f"delta {delta:+.2f}% ({'improvement' if delta > 0 else 'regression'})\n")

    print("--- Calibration by line (WITH absence_rate_r10) ---\n")
    for line in LINES:
        raw_p = 1 - poisson.cdf(np.floor(line), pred_mu)
        actual = (test["saves_actual"].values > line).astype(int)
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
