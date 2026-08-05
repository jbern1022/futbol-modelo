"""
Train, gate, persist and register the props models.

    python scripts/train_props_models.py                 # all markets
    python scripts/train_props_models.py --market CORNERS
    python scripts/train_props_models.py --dry-run       # evaluate, save nothing

This is the only place a props model is fitted. The slate generator loads the
artifacts this produces; it does not train. Previously it refit a fresh model
per fixture per market, which made predictions unreproducible, filled
model_versions with one meaningless row per fixture, and left no place for a
calibrator to live — so raw uncalibrated Poisson probabilities went to the
ledger.

THE GATE
The README claims each props model is "required to beat a naive baseline on
held-out data before being allowed to ship". That gate existed only in offline
analysis scripts, never in the path that shipped. It is enforced here: the
model is fit on everything before a time cutoff, scored against the naive
train-mean baseline on everything after it, and a model that fails is NOT
saved and NOT registered. The exit status is non-zero so a scheduled run fails
loudly rather than quietly leaving yesterday's artifact in place.

A model that passes is then refit on the full history — validation decides
whether to ship, the shipped artifact should still learn from every match —
registered in futbol.model_versions, and written to $FUTBOL_MODEL_DIR.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.props import (  # noqa: E402
    MARKETS,
    artifact_path,
    baseline_logloss,
    for_market,
    poisson_logloss,
)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
MODEL_DIR = os.environ.get("FUTBOL_MODEL_DIR", "models")
HOLDOUT_FRACTION = 0.20


def load(conn, market: str) -> pd.DataFrame:
    spec = MARKETS[market]
    cols = spec["features"]
    select = ", ".join(f"f.{c}" for c in cols)
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT l.code AS league, f.kickoff_utc, {select},
                   tms.{spec['target_col']} AS y
            FROM futbol.team_match_features f
            JOIN futbol.leagues l ON l.league_id = f.league_id
            JOIN futbol.team_match_stats tms
              ON tms.match_id = f.match_id AND tms.team_id = f.team_id
            WHERE tms.{spec['target_col']} IS NOT NULL
            ORDER BY f.kickoff_utc
        """)
        rows = cur.fetchall()
        names = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=names)
    for c in cols + ["y"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=cols + ["y"]).reset_index(drop=True)


def evaluate(market: str, df: pd.DataFrame) -> dict:
    """Fit on the earlier portion, score on the later one. Time-ordered, so
    the holdout is genuinely unseen future matches rather than a random slice."""
    cut = int(len(df) * (1 - HOLDOUT_FRACTION))
    train, test = df.iloc[:cut], df.iloc[cut:]
    model = for_market(market).fit(train, "y")

    mu = np.clip(model.model.predict(test[model.features]), 1e-6, None)
    y = test["y"].to_numpy()
    model_ll = poisson_logloss(y, mu)
    base_ll = baseline_logloss(y, float(train["y"].mean()))
    return {
        "n_train": int(len(train)),
        "n_holdout": int(len(test)),
        "holdout_logloss": round(model_ll, 5),
        "baseline_logloss": round(base_ll, 5),
        "improvement": round(base_ll - model_ll, 5),
        "holdout_mae": round(float(np.abs(y - mu).mean()), 4),
        "beats_baseline": bool(model_ll < base_ll),
        "holdout_from": str(test["kickoff_utc"].min()),
        "holdout_to": str(test["kickoff_utc"].max()),
    }


def register(conn, market: str, version_tag: str, df: pd.DataFrame,
             metrics: dict) -> int:
    spec = MARKETS[market]
    window = f"{df['kickoff_utc'].min()}..{df['kickoff_utc'].max()}"
    params = {"features": spec["features"], "categorical": spec["categorical"],
              "lines": spec["lines"], "target": spec["target_col"],
              "leagues": sorted(df["league"].unique().tolist())}
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO futbol.model_versions
                 (model_name, version_tag, training_window, params, train_metrics)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (model_name, version_tag) DO UPDATE
                 SET train_metrics = EXCLUDED.train_metrics,
                     params = EXCLUDED.params,
                     training_window = EXCLUDED.training_window
               RETURNING model_version_id""",
            (f"props_{market.lower()}", version_tag, window,
             json.dumps(params), json.dumps(metrics)))
        model_version_id = cur.fetchone()[0]
    conn.commit()
    return model_version_id


def train_one(conn, market: str, version_tag: str, dry_run: bool) -> bool:
    print(f"\n=== {market} " + "=" * (60 - len(market)))
    df = load(conn, market)
    if df.empty:
        print("  no usable rows — skipping")
        return False
    by_league = df.groupby("league").size().to_dict()
    print(f"  {len(df)} trainable rows  {by_league}")

    metrics = evaluate(market, df)
    print(f"  holdout {metrics['n_holdout']} rows "
          f"({metrics['holdout_from'][:10]} .. {metrics['holdout_to'][:10]})")
    print(f"  logloss  model={metrics['holdout_logloss']:.5f}  "
          f"baseline={metrics['baseline_logloss']:.5f}  "
          f"improvement={metrics['improvement']:+.5f}")

    if not metrics["beats_baseline"]:
        print("  REFUSING TO SHIP: does not beat the naive baseline.")
        print("  Nothing saved, nothing registered. Existing artifact untouched.")
        return False

    if dry_run:
        print("  passes the gate (dry run — nothing written)")
        return True

    model_version_id = register(conn, market, version_tag, df, metrics)
    model = for_market(market).fit(df, "y")
    model.metadata.update({
        "model_version_id": model_version_id,
        "version_tag": version_tag,
        "model_name": f"props_{market.lower()}",
        "holdout_metrics": metrics,
    })
    path = model.save(artifact_path(MODEL_DIR, market))
    print(f"  calibrated lines: {model.metadata['calibrated_lines']}")
    print(f"  saved {path}  (model_version_id={model_version_id}, "
          f"version_tag={version_tag})")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="all",
                    choices=list(MARKETS) + ["all"])
    ap.add_argument("--dry-run", action="store_true",
                    help="evaluate and report, write no artifact or registry row")
    args = ap.parse_args()

    version_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    markets = list(MARKETS) if args.market == "all" else [args.market]

    conn = psycopg2.connect(DSN)
    try:
        results = {m: train_one(conn, m, version_tag, args.dry_run) for m in markets}
    finally:
        conn.close()

    failed = [m for m, ok in results.items() if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} market(s) "
          f"{'passed' if not args.dry_run else 'would pass'} the gate")
    if failed:
        print(f"failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
