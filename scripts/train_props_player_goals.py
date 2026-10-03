"""
Player goals-scorer props model — now with real multi-season depth
(6 MLS seasons backfilled with player-level stats). Uses the same
season-holdout discipline as the team-level props models: train on
2021-2025, test on the held-out 2026 season.

    python scripts/train_props_player_goals.py
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
    f.p_shots_r5, f.p_minutes_r5, f.p_goals_r10, f.p_key_passes_r5,
    pif.absence_rate_r10,
    p.full_name, th.name AS team_name, s.label AS season,
    CASE WHEN f.team_id = m.home_team_id THEN ta.name ELSE th2.name END AS opponent,
    m.kickoff_utc,
    pms.goals AS goals_actual
FROM futbol.player_match_features f
JOIN futbol.matches m ON m.match_id = f.match_id
JOIN futbol.players p ON p.player_id = f.player_id
JOIN futbol.teams th ON th.team_id = f.team_id
JOIN futbol.teams th2 ON th2.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.player_match_stats pms ON pms.match_id = f.match_id AND pms.player_id = f.player_id
LEFT JOIN futbol.player_injury_features pif
  ON pif.match_id = f.match_id AND pif.player_id = f.player_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = 'MLS' AND pms.minutes >= 45
ORDER BY m.kickoff_utc;
"""

# Baseline is the live features as of before the lineup/injury-news
# feature (Todoist: "futbol-modelo: lineup/injury news as a model
# feature"); WITH_ABSENCE is the candidate this A/B is gating before
# generate_slate.py's fit_player_goals_model() gets to rely on it live
# -- same discipline CARDS' referee_avg_cards_r10 went through
# (scripts/train_props.py) before being wired in.
FEATURES = ["p_shots_r5", "p_minutes_r5", "p_goals_r10", "p_key_passes_r5"]
FEATURES_WITH_ABSENCE = FEATURES + ["absence_rate_r10"]
LINES = [0.5, 1.5]


def main():
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn)
    conn.close()

    df[FEATURES_WITH_ABSENCE] = df[FEATURES_WITH_ABSENCE].apply(pd.to_numeric, errors="coerce")
    df_base = df.dropna(subset=FEATURES + ["goals_actual"])
    df_absence = df.dropna(subset=FEATURES_WITH_ABSENCE + ["goals_actual"])
    print(f"\n{len(df_base)} player-match rows across {df_base['season'].nunique()} seasons "
          f"(players with >=45 min, complete rolling features)\n")
    print(f"{len(df_absence)} rows also have absence_rate_r10 populated "
          f"(player_injury_features requires >=5 career team appearances)\n")

    def poisson_log_loss(y_true, mu):
        mu = np.clip(mu, 1e-6, None)
        return -np.mean(poisson.logpmf(y_true.astype(int), mu))

    def run(df_variant, features, label):
        train = df_variant[df_variant.season != HOLDOUT_SEASON]
        test = df_variant[df_variant.season == HOLDOUT_SEASON]
        model = lgb.LGBMRegressor(objective="poisson", n_estimators=300, learning_rate=0.03,
                                  num_leaves=20, min_child_samples=30, verbose=-1)
        model.fit(train[features], train["goals_actual"])
        pred_mu = np.clip(model.predict(test[features]), 0.02, None)
        baseline_mu = train["goals_actual"].mean()
        model_ll = poisson_log_loss(test["goals_actual"], pred_mu)
        baseline_ll = poisson_log_loss(test["goals_actual"], np.full(len(test), baseline_mu))
        improvement = (baseline_ll - model_ll) / baseline_ll * 100
        print(f"--- {label}: train {len(train)}, test {len(test)} "
              f"(held-out season {HOLDOUT_SEASON}) ---")
        print(f"Naive baseline ({baseline_mu:.3f} goals/appearance): log-loss {baseline_ll:.3f}")
        print(f"Model log-loss: {model_ll:.3f} "
              f"({'BEATS' if model_ll < baseline_ll else 'does NOT beat'} baseline, "
              f"{improvement:+.1f}%)\n")
        return model, pred_mu, test, model_ll

    model_base, _, _, ll_base = run(df_base, FEATURES, "WITHOUT absence_rate_r10 (current live)")
    model, pred_mu, test, ll_absence = run(
        df_absence, FEATURES_WITH_ABSENCE, "WITH absence_rate_r10 (candidate)")
    delta = (ll_base - ll_absence) / ll_base * 100
    print("--- A/B: absence_rate_r10 vs current live features ---")
    print(f"WITHOUT: log-loss {ll_base:.4f}   WITH: log-loss {ll_absence:.4f}   "
          f"delta {delta:+.2f}% ({'improvement' if delta > 0 else 'regression'})\n")

    print("--- Anytime goalscorer calibration (WITH absence_rate_r10) ---\n")
    for line in LINES:
        raw_p = 1 - poisson.cdf(np.floor(line), pred_mu)
        actual = (test["goals_actual"].values > line).astype(int)
        print(f"Over {line} goals: avg stated {raw_p.mean():.1%}, "
              f"realized {actual.mean():.1%} (n={len(actual)})")

    print("\n--- Sample predictions (held-out season) ---\n")
    test = test.copy()
    test["predicted_goals"] = pred_mu
    shown = test[test["predicted_goals"] > 0.3].head(8)
    for _, row in shown.iterrows():
        print(f"{row['full_name']:<22} ({row['team_name']:<18} vs {row['opponent']:<18}): "
              f"predicted {row['predicted_goals']:.2f}, actual {int(row['goals_actual'])}")


if __name__ == "__main__":
    main()
