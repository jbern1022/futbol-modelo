"""
Custom xG model from event-level shot data (Phase G / the "v3 plan"
referenced in loader.py's shots-ingestion comment). Understat's own xG
(shots.source_xg) is the benchmark this is scored against -- the real
question this script answers honestly is whether a model trained on
this project's own data actually beats it, not whether it looks
plausible.

    python scripts/train_xg_model.py --league EPL
    python scripts/train_xg_model.py --league BOTH

Held-out season evaluation (log loss + Brier score on goal/no-goal),
same walk-forward-adjacent discipline as train_props_corners.py: train
on all prior seasons, test on the most recent complete one, never
shuffled across time.

Scope note: this only covers leagues Understat actually has shot data
for (EPL, SERIE_A, LA_LIGA) -- MLS has no shot-level (x, y, situation,
body_part) ingestion at all yet (Understat doesn't cover MLS, and no
other source's shot-events are wired in). "Removes dependence on a
source that doesn't cover MLS" -- the model itself does, once it
exists -- but actually running it on MLS fixtures needs a new MLS
shot-event ingestion pipeline first, which this script does not build.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
from sklearn.metrics import brier_score_loss, log_loss

lgb: Any
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Excludes 'Own Goal' -- not a shot attempt by the listed player in any
# normal xG sense (the shooter and the "shot" outcome belong to the
# wrong end of the pitch conceptually), and negligible in volume
# (374 of 107,323 rows) to matter either way.
Q = """
SELECT s.x, s.y, s.situation, s.body_part, s.result, s.source_xg,
       m.kickoff_utc::date AS kickoff_date, se.label AS season, l.code AS league
FROM futbol.shots s
JOIN futbol.matches m ON m.match_id = s.match_id
JOIN futbol.seasons se ON se.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = se.league_id
WHERE l.code = ANY(%s) AND s.result <> 'Own Goal'
ORDER BY m.kickoff_utc;
"""

# Understat's normalized-coordinate convention: x in [0,1] is 0-105m
# along the pitch, 1 = the byline at the goal being shot at; y in [0,1]
# is 0-68m across the pitch, 0.5 = the pitch's centerline. Distance and
# angle-to-goal are standard xG feature-engineering derivations from
# these raw coordinates -- a GBM works far better on physically
# meaningful geometry than on raw (x, y) alone.
PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
GOAL_WIDTH_M = 7.32


def add_geometry_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    dx = (1 - df["x"]) * PITCH_LENGTH_M
    dy = (df["y"] - 0.5) * PITCH_WIDTH_M
    df["distance_m"] = np.sqrt(dx**2 + dy**2)

    # Angle subtended by the goal mouth from the shot location -- the
    # standard shot-geometry formula (law-of-cosines derived), not just
    # "angle to the center of the goal". A shot dead level with the
    # goal line 1m out has a huge angle even though dx~0; this captures
    # that, plain center-angle would not.
    half_goal = GOAL_WIDTH_M / 2
    numerator = 2 * half_goal * dx
    denominator = dx**2 + dy**2 - half_goal**2
    df["angle_rad"] = np.abs(np.arctan2(numerator, denominator))
    return df


# Understat encodes penalties as a fixed spot (x=0.885, y=0.500,
# situation=NULL) with a fixed benchmark xG (0.7613 -- the known
# historical penalty conversion rate, not a per-shot model output).
# distance_m/angle_rad alone land right on that exact point for every
# penalty, so a GBM given enough of them CAN learn the constant --
# but an explicit flag makes it certain rather than hoping the trees
# split on it, and there's no literal "Penalty" situation value to use
# instead (checked directly: situation is always NULL for these).
_PENALTY_X, _PENALTY_Y = 0.885, 0.500


def add_penalty_flag(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_penalty"] = (
        (df["x"] - _PENALTY_X).abs().lt(0.001) & (df["y"] - _PENALTY_Y).abs().lt(0.001)
    ).astype(int)
    return df


FEATURES = ["distance_m", "angle_rad", "situation", "body_part", "is_penalty"]
CATEGORICAL = ["situation", "body_part"]
HOLDOUT_SEASON = "2025-26"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA", "BOTH"])
    args = ap.parse_args()

    if lgb is None:
        raise SystemExit("lightgbm not installed")

    leagues = ["EPL", "SERIE_A", "LA_LIGA"] if args.league == "BOTH" else [args.league]

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(leagues,))
    conn.close()

    df["is_goal"] = (df["result"] == "Goal").astype(int)
    df["situation"] = df["situation"].fillna("Unknown").astype("category")
    # No literal "Header" value exists in this source's body_part field
    # -- checked directly, only 'Right Foot'/'Left Foot'/NULL appear.
    # NULL is ~18% of all shots, too large a share to be missing data;
    # treated as its own category (almost certainly headers) rather
    # than dropped or silently merged into a foot category.
    df["body_part"] = df["body_part"].fillna("Other/Head").astype("category")
    df = add_geometry_features(df)
    df = add_penalty_flag(df)

    print(f"\n{len(df)} shots across {df['season'].nunique()} seasons "
          f"({', '.join(leagues)})\n")

    train = df[df.season != HOLDOUT_SEASON]
    test = df[df.season == HOLDOUT_SEASON]
    print(f"Train: {len(train)} shots (seasons {sorted(train.season.unique())})")
    print(f"Test:  {len(test)} shots (held-out season {HOLDOUT_SEASON})\n")

    X_train, y_train = train[FEATURES], train["is_goal"]
    X_test, y_test = test[FEATURES], test["is_goal"]

    model = lgb.LGBMClassifier(
        objective="binary", n_estimators=300, learning_rate=0.03,
        num_leaves=20, min_child_samples=30, subsample=0.8,
        colsample_bytree=0.8, verbose=-1,
    )
    model.fit(X_train, y_train, categorical_feature=CATEGORICAL)
    our_xg = model.predict_proba(X_test)[:, 1]
    understat_xg = test["source_xg"].to_numpy()

    our_ll = log_loss(y_test, our_xg, labels=[0, 1])
    understat_ll = log_loss(y_test, understat_xg, labels=[0, 1])
    our_brier = brier_score_loss(y_test, our_xg)
    understat_brier = brier_score_loss(y_test, understat_xg)

    print(f"--- Held-out season evaluation: our xG vs Understat's xG "
          f"(n={len(test)} shots, {int(y_test.sum())} goals) ---\n")
    print(f"{'':20s} {'log loss':>10s}   {'Brier':>10s}")
    print(f"{'Our model':20s} {our_ll:>10.4f}   {our_brier:>10.4f}")
    print(f"{'Understat xG':20s} {understat_ll:>10.4f}   {understat_brier:>10.4f}")

    ll_diff_pct = (understat_ll - our_ll) / understat_ll * 100
    verdict = "BEATS" if our_ll < understat_ll else "does NOT beat"
    print(f"\n-> Our model {verdict} Understat's xG on log loss "
          f"({ll_diff_pct:+.1f}%)\n")

    print("--- Calibration by predicted-probability decile (our model) ---\n")
    test = test.copy()
    test["our_xg"] = our_xg
    test["decile"] = pd.qcut(test["our_xg"], q=10, duplicates="drop")
    calib = test.groupby("decile", observed=True).agg(
        n=("is_goal", "size"), stated=("our_xg", "mean"), realized=("is_goal", "mean"))
    for _, row in calib.iterrows():
        print(f"  stated {row['stated']:.1%} -> realized {row['realized']:.1%} "
              f"(n={int(row['n'])})")

    print("\n--- Feature importance ---\n")
    importances = sorted(
        zip(FEATURES, model.feature_importances_), key=lambda x: -x[1])
    for feat, imp in importances:
        print(f"  {feat:15s} {imp}")


if __name__ == "__main__":
    main()
