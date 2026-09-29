"""
Todoist: "Experiment: compare Elo and alternative models with
Dixon-Coles for soccer 1X2" -- Phase 1 only (steps 2-4 are explicitly
conditional on Phase 1 finding complementary/persistent errors, per
the ticket's own text: "If complementary errors exist..." / "Only if
persistent...").

Question: can an independent outcome-rating signal (Elo) improve or
complement Dixon-Coles' 1X2 probabilities? Fits a standalone Elo model
(ratings updated match-by-match, in chronological order, so every
rating used to predict a match reflects only STRICTLY PRIOR results --
no lookahead) and maps the pre-match Elo difference to 1X2 probabilities
via multinomial logistic regression, refit on the SAME weekly cadence
and SAME train/holdout split walk-forward harness scripts/train_dixon_coles.py
already uses, so RPS/log-loss/accuracy are directly comparable, not
just similar-shaped numbers from a different evaluation.

    python scripts/experiment_elo_vs_dixon_coles.py --league EPL --holdout 2025-26
    python scripts/experiment_elo_vs_dixon_coles.py --league EPL --holdout 2025-26 --k-grid
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression

from dixon_coles import DixonColes, derive_markets
from train_dixon_coles import Q, rps, walk_forward as dc_walk_forward  # noqa: E402

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

START_ELO = 1500.0
HOME_ADV = 100.0   # standard published World Football Elo Ratings value, not tuned here


def compute_elo_diffs(df: pd.DataFrame, k: float) -> pd.DataFrame:
    """
    Single chronological pass over the WHOLE match history (train +
    holdout together -- a team's Elo rating has to accumulate
    continuously across that boundary to mean anything, unlike
    Dixon-Coles' from-scratch weekly refit). Records each match's
    PRE-match elo_diff = elo_home + HOME_ADV - elo_away, i.e. the value
    known at forecast time, strictly before that match's own result
    updates either team's rating -- the leakage-safety the ticket asks
    for ("using only matches and features known at each forecast
    timestamp").
    """
    elo: dict[str, float] = {}
    diffs = []
    for row in df.itertuples():
        eh = elo.setdefault(row.home, START_ELO)
        ea = elo.setdefault(row.away, START_ELO)
        diffs.append(eh + HOME_ADV - ea)

        expected_home = 1.0 / (1.0 + 10 ** (-(eh + HOME_ADV - ea) / 400.0))
        actual_home = 1.0 if row.hg > row.ag else (0.5 if row.hg == row.ag else 0.0)
        elo[row.home] = eh + k * (actual_home - expected_home)
        elo[row.away] = ea + k * ((1 - actual_home) - (1 - expected_home))
    out = df.copy()
    out["elo_diff"] = diffs
    return out


def elo_walk_forward(df: pd.DataFrame, holdout: str, k: float) -> dict:
    """Same weekly-refit walk-forward shape as train_dixon_coles.py's
    walk_forward() -- refits the elo_diff -> 1X2 mapping every 7 days
    using every match strictly before that point (pre-holdout seasons
    plus already-elapsed holdout matches), same as Dixon-Coles' own
    from-scratch weekly refit, for a fair RPS/log-loss comparison."""
    df = compute_elo_diffs(df, k)
    test = df[df.season == holdout].copy()
    if test.empty:
        raise SystemExit(f"no matches found for holdout season {holdout}")

    scores, lls, correct = [], [], 0
    refit_at = None
    clf = None
    for _, row in test.iterrows():
        if refit_at is None or row.date >= refit_at:
            past = df[df.date < row.date]
            # Multinomial logistic on a single scalar feature (elo_diff)
            # -- deliberately simple (the ticket calls this an
            # "independent outcome-rating signal" test, not a full
            # feature-rich model); classes fixed as [0,1,2]=[home,draw,away]
            # so predict_proba's column order is always the same even if
            # a training split happens to be missing an outcome class.
            y = np.select([past.hg > past.ag, past.hg == past.ag], [0, 1], default=2)
            clf = LogisticRegression(max_iter=1000)  # sklearn's lbfgs solver is multinomial by default for >2 classes
            clf.fit(past[["elo_diff"]].values, y)
            for c in (0, 1, 2):
                if c not in clf.classes_:
                    clf = None  # degenerate split (e.g. all-home-wins) -- skip until it isn't
                    break
            refit_at = row.date + timedelta(days=7)
        if clf is None:
            continue
        proba = dict(zip(clf.classes_, clf.predict_proba([[row.elo_diff]])[0]))
        p = [proba.get(0, 0.0), proba.get(1, 0.0), proba.get(2, 0.0)]
        actual = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)
        scores.append(rps(p, actual))
        lls.append(-np.log(max(p[actual], 1e-9)))
        correct += int(np.argmax(p) == actual)

    n = len(scores)
    if n == 0:
        return {"n": 0, "rps": None, "log_loss": None, "accuracy": None, "k": k}
    return {"n": n, "rps": round(float(np.mean(scores)), 4),
            "log_loss": round(float(np.mean(lls)), 4),
            "accuracy": round(correct / n, 4), "k": k}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--holdout", default="2025-26")
    ap.add_argument("--k", type=float, default=20.0)
    ap.add_argument("--k-grid", action="store_true")
    ap.add_argument("--xi", type=float, default=0.0018, help="Dixon-Coles xi for the baseline column")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=(args.league,))
    df["date"] = pd.to_datetime(df["date"])
    conn.close()
    print(f"loaded {len(df)} finals for {args.league} "
          f"(seasons: {sorted(df.season.unique())})\n")

    dc = dc_walk_forward(df, args.holdout, args.xi)
    print(f"Dixon-Coles (xi={args.xi}): {json.dumps(dc)}")

    grid = [10.0, 15.0, 20.0, 30.0, 40.0] if args.k_grid else [args.k]
    elo_results = [elo_walk_forward(df, args.holdout, k) for k in grid]
    for r in elo_results:
        print(f"Elo (k={r['k']}):{' ' * (10 - len(str(r['k'])))}{json.dumps(r)}")

    valid = [r for r in elo_results if r["rps"] is not None]
    if not valid:
        print("\nNo valid Elo result (degenerate splits throughout) -- can't compare.")
        return
    best_elo = min(valid, key=lambda r: r["rps"])

    print(f"\n--- {args.league} {args.holdout}: Dixon-Coles vs best Elo (RPS, lower=better) ---")
    print(f"Dixon-Coles: RPS {dc['rps']}, log-loss {dc['log_loss']}, "
          f"accuracy {dc['accuracy']} (n={dc['n']})")
    print(f"Elo (k={best_elo['k']}): RPS {best_elo['rps']}, log-loss {best_elo['log_loss']}, "
          f"accuracy {best_elo['accuracy']} (n={best_elo['n']})")
    if best_elo["rps"] < dc["rps"]:
        print("-> Elo BEATS Dixon-Coles on RPS in this league/holdout "
              "(worth investigating a blend, per the ticket's step 2).")
    else:
        print("-> Dixon-Coles still wins. Elo alone is not a replacement here "
              "(a blend may still help if errors are complementary -- not tested by this script).")


if __name__ == "__main__":
    main()
