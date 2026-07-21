"""
Generic props trainer — same rigor as train_props_corners.py but
parameterized by market, so corners/SOT/cards share one implementation.
Default league scope is BOTH (cross-league training won yesterday).

    python scripts/train_props.py --market CORNERS
    python scripts/train_props.py --market SOT
    python scripts/train_props.py --market CARDS
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
HOLDOUT_SEASON = "2025-26"

MARKETS = {
    "CORNERS": {
        "target_col": "corners",
        "features": ["corners_for_r5", "corners_against_r5", "shots_for_r5",
                    "shots_against_r5", "xg_for_r5", "xg_against_r5",
                    "rest_days", "is_home"],
        "lines": [3.5, 4.5, 5.5, 6.5],
    },
    "SOT": {
        "target_col": "shots_on_target",
        "features": ["sot_for_r5", "sot_against_r5", "shots_for_r5",
                    "shots_against_r5", "xg_for_r5", "xg_against_r5",
                    "rest_days", "is_home"],
        "lines": [2.5, 3.5, 4.5, 5.5],
    },
    "CARDS": {
        "target_col": "yellows",
        "features": ["yellows_for_r5", "fouls_for_r5", "reds_for_r5",
                    "rest_days", "is_home"],
        "lines": [1.5, 2.5, 3.5],
    },
}

Q = """
SELECT
    f.match_id, f.team_id, f.kickoff_utc,
    {feature_cols},
    s.label AS season, l.code AS league,
    th.name AS team_name,
    CASE WHEN f.is_home THEN ta.name ELSE th2.name END AS opponent,
    tms.{target_col} AS target_actual
FROM futbol.team_match_features f
JOIN futbol.matches m ON m.match_id = f.match_id
JOIN futbol.teams th ON th.team_id = f.team_id
JOIN futbol.teams th2 ON th2.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.team_match_stats tms ON tms.match_id = f.match_id AND tms.team_id = f.team_id
WHERE l.code = ANY(%s) AND tms.{target_col} IS NOT NULL
ORDER BY f.kickoff_utc;
"""


def poisson_log_loss(y_true, mu):
    mu = np.clip(mu, 1e-6, None)
    return -np.mean(poisson.logpmf(y_true.astype(int), mu))


def fit_model(X, y):
    return lgb.LGBMRegressor(
        objective="poisson", n_estimators=300, learning_rate=0.03,
        num_leaves=20, min_child_samples=30, subsample=0.8,
        colsample_bytree=0.8, verbose=-1,
    ).fit(X, y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=list(MARKETS))
    ap.add_argument("--league", default="BOTH", choices=["SERIE_A", "EPL", "BOTH"])
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args()

    if lgb is None:
        raise SystemExit("lightgbm not installed")

    spec = MARKETS[args.market]
    features, target_col, lines = spec["features"], spec["target_col"], spec["lines"]
    leagues = ["SERIE_A", "EPL"] if args.league == "BOTH" else [args.league]

    feature_cols = ", ".join(f"f.{c}" for c in features)
    query = Q.format(feature_cols=feature_cols, target_col=target_col)

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(query, conn, params=(leagues,))

    df["is_home"] = df["is_home"].astype(int)
    df = df.dropna(subset=features + ["target_actual"])
    print(f"\n[{args.market} / {args.league}] {len(df)} rows, "
          f"{df['season'].nunique()} seasons\n")

    train = df[df.season != HOLDOUT_SEASON]
    test = df[df.season == HOLDOUT_SEASON]
    print(f"Train: {len(train)} rows  |  Test: {len(test)} rows "
          f"(held-out {HOLDOUT_SEASON})\n")

    X_train, y_train = train[features], train["target_actual"]
    X_test, y_test = test[features], test["target_actual"]

    model = fit_model(X_train, y_train)
    pred_mu = np.clip(model.predict(X_test), 0.05, None)
    baseline_mu = y_train.mean()

    model_ll = poisson_log_loss(y_test, pred_mu)
    baseline_ll = poisson_log_loss(y_test, np.full(len(y_test), baseline_mu))
    improvement = (baseline_ll - model_ll) / baseline_ll * 100
    beats = bool(model_ll < baseline_ll)

    print(f"Baseline ({baseline_mu:.2f}/match): log-loss {baseline_ll:.3f}")
    print(f"Model:                     log-loss {model_ll:.3f}")
    print(f"-> {'BEATS' if beats else 'does NOT beat'} baseline "
          f"({improvement:+.1f}%)\n")

    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof_mu = np.full(len(train), np.nan)
    Xt, yt = X_train.reset_index(drop=True), y_train.reset_index(drop=True)
    for tr_idx, val_idx in kf.split(Xt):
        fold_model = fit_model(Xt.iloc[tr_idx], yt.iloc[tr_idx])
        oof_mu[val_idx] = fold_model.predict(Xt.iloc[val_idx])
    oof_mu = np.clip(oof_mu, 0.05, None)

    line_results = {}
    print("--- Calibration by line ---\n")
    for line in lines:
        raw_p_train = 1 - poisson.cdf(np.floor(line), oof_mu)
        actual_train = (yt.values > line).astype(int)
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        calibrator.fit(raw_p_train, actual_train)

        raw_p_test = 1 - poisson.cdf(np.floor(line), pred_mu)
        calibrated_p_test = calibrator.predict(raw_p_test)
        actual_test = (y_test.values > line).astype(int)

        def gap(probs):
            buckets = pd.qcut(probs, q=4, duplicates="drop")
            g = pd.DataFrame({"b": buckets, "s": probs, "a": actual_test})
            summ = g.groupby("b", observed=True).agg(s=("s", "mean"), a=("a", "mean"))
            return (summ["a"] - summ["s"]).abs().mean()

        raw_gap, calib_gap = gap(raw_p_test), gap(calibrated_p_test)
        use_calib = raw_gap > 0.05 and calib_gap < raw_gap
        line_results[line] = {"raw_gap": round(raw_gap, 4), "calib_gap": round(calib_gap, 4),
                              "use_calibration": bool(use_calib)}
        print(f"  Over {line}: raw gap {raw_gap:.1%} -> calibrated gap {calib_gap:.1%} "
              f"({'USE CALIBRATED' if use_calib else 'USE RAW'})")

    print("\n--- Sample predictions ---\n")
    test = test.copy()
    test["predicted"] = pred_mu
    for _, row in test.head(5).iterrows():
        venue = "home" if row["is_home"] else "away"
        print(f"{row['team_name']:<20} vs {row['opponent']:<20} ({venue}, {row['league']}): "
              f"predicted {row['predicted']:.2f}, actual {int(row['target_actual'])}")

    if args.register:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO futbol.model_versions
                     (model_name, version_tag, training_window, params, train_metrics)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (model_name, version_tag)
                   DO UPDATE SET train_metrics = EXCLUDED.train_metrics
                   RETURNING model_version_id""",
                (f"props_{args.market.lower()}_lgbm", f"v1_{args.league.lower()}",
                 "2021-22_through_2024-25",
                 json.dumps({"league_scope": args.league, "lines": lines,
                            "calibration": "isotonic_5fold_oof"}),
                 json.dumps({"log_loss_improvement_pct": round(improvement, 2),
                            "beats_baseline": beats, "n_train": len(train),
                            "n_test": len(test), "lines": line_results})))
            mvid = cur.fetchone()[0]
            conn.commit()
            print(f"\nRegistered model_version_id={mvid}")

    conn.close()


if __name__ == "__main__":
    main()
