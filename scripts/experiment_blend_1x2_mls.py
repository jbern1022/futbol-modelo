"""
Todoist `6hf55hCCX78Wc6m7`, Phase 1 step 2 -- MLS only. Phase 1
(scripts/experiment_elo_vs_dixon_coles.py, 2026-09-29) found Elo beats
Dixon-Coles on BOTH RPS and log-loss for MLS specifically (not just one
metric, and not for EPL/SERIE_A/LA_LIGA) -- the "complementary errors"
trigger this ticket's step 2 asks for before testing a blend.

Methodology, per the ticket's own explicit requirement: "learn weights
only on earlier walk-forward validation periods and score on later
untouched seasons." Concretely:
  - VALIDATION_SEASON (2025): both models walk-forward through this
    season as usual (weekly refit on strictly-prior data), producing
    paired (p_dixon_coles, p_elo, actual) triples. The blend weight
    alpha is swept and picked HERE, minimizing RPS.
  - TEST_SEASON (2026): the actual holdout, never touched by alpha
    selection. DC alone / Elo alone / blend(best alpha) are all scored
    here for the real out-of-sample comparison.

    python scripts/experiment_blend_1x2_mls.py
"""
from __future__ import annotations

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
from train_dixon_coles import Q, rps
from experiment_elo_vs_dixon_coles import compute_elo_diffs, HOME_ADV  # noqa: E402, F401

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
VALIDATION_SEASON = "2025"
TEST_SEASON = "2026"
DC_XI = 0.0018
ELO_K = 40.0   # best from Phase 1's grid for MLS


def collect_paired(df_elo: pd.DataFrame, season: str) -> list[tuple[list[float], list[float], int]]:
    """Walks forward through `season` refitting BOTH models weekly on
    the same strictly-prior training history, returning paired
    (p_dixon_coles, p_elo, actual_outcome_idx) per match -- the raw
    material both alpha selection (on validation) and final scoring
    (on test) are built from."""
    test = df_elo[df_elo.season == season].copy()
    if test.empty:
        return []

    pairs = []
    refit_at = None
    dc_model = None
    elo_clf = None
    for _, row in test.iterrows():
        if refit_at is None or row.date >= refit_at:
            past = df_elo[df_elo.date < row.date]
            dc_model = DixonColes(xi=DC_XI).fit(
                past.rename(columns=str).assign(date=pd.to_datetime(past.date)))
            y = np.select([past.hg > past.ag, past.hg == past.ag], [0, 1], default=2)
            elo_clf = LogisticRegression(max_iter=1000)
            elo_clf.fit(past[["elo_diff"]].values, y)
            if not all(c in elo_clf.classes_ for c in (0, 1, 2)):
                elo_clf = None
            refit_at = row.date + timedelta(days=7)
        if dc_model is None or elo_clf is None:
            continue
        try:
            mk = derive_markets(dc_model.predict(row.home, row.away))
        except KeyError:      # promoted team with no history yet
            continue
        p_dc = [mk["home_win"], mk["draw"], mk["away_win"]]
        proba = dict(zip(elo_clf.classes_, elo_clf.predict_proba([[row.elo_diff]])[0]))
        p_elo = [proba.get(0, 0.0), proba.get(1, 0.0), proba.get(2, 0.0)]
        actual = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)
        pairs.append((p_dc, p_elo, actual))
    return pairs


def score(pairs: list, alpha: float | None) -> dict:
    """alpha=None means Dixon-Coles alone; alpha=0 means Elo alone;
    otherwise p = alpha*p_dc + (1-alpha)*p_elo."""
    scores, lls, correct = [], [], 0
    for p_dc, p_elo, actual in pairs:
        if alpha is None:
            p = p_dc
        else:
            p = [alpha * a + (1 - alpha) * b for a, b in zip(p_dc, p_elo)]
            total = sum(p)
            p = [x / total for x in p]
        scores.append(rps(p, actual))
        lls.append(-np.log(max(p[actual], 1e-9)))
        correct += int(np.argmax(p) == actual)
    n = len(scores)
    if n == 0:
        return {"n": 0, "rps": None, "log_loss": None, "accuracy": None}
    return {"n": n, "rps": round(float(np.mean(scores)), 4),
            "log_loss": round(float(np.mean(lls)), 4), "accuracy": round(correct / n, 4)}


def main():
    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=("MLS",))
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df_elo = compute_elo_diffs(df, ELO_K)
    print(f"loaded {len(df)} MLS finals (seasons: {sorted(df.season.unique())})\n")

    print(f"--- Step A: learn alpha on VALIDATION season {VALIDATION_SEASON} only ---")
    val_pairs = collect_paired(df_elo, VALIDATION_SEASON)
    print(f"{len(val_pairs)} validation matches\n")
    alpha_grid = [round(a, 1) for a in np.arange(0.0, 1.01, 0.1)]
    val_scores = [(a, score(val_pairs, a)) for a in alpha_grid]
    for a, s in val_scores:
        print(f"alpha={a}: {json.dumps(s)}")
    best_alpha = min(val_scores, key=lambda t: t[1]["rps"])[0]
    print(f"\nBest alpha on validation: {best_alpha} "
          f"(alpha=1.0 is pure Dixon-Coles, alpha=0.0 is pure Elo)\n")

    print(f"--- Step B: score on TEST season {TEST_SEASON} (untouched by alpha selection) ---")
    test_pairs = collect_paired(df_elo, TEST_SEASON)
    dc_only = score(test_pairs, 1.0)
    elo_only = score(test_pairs, 0.0)
    blend = score(test_pairs, best_alpha)
    print(f"Dixon-Coles alone:      {json.dumps(dc_only)}")
    print(f"Elo alone:              {json.dumps(elo_only)}")
    print(f"Blend (alpha={best_alpha}):        {json.dumps(blend)}")

    print("\n--- Verdict ---")
    best_single = dc_only if dc_only["rps"] <= elo_only["rps"] else elo_only
    if blend["rps"] < best_single["rps"]:
        print(f"Blend BEATS the best single model on the untouched test season "
              f"({blend['rps']} < {best_single['rps']}) -- gain is real, not an artifact "
              f"of tuning on the same data being scored.")
    else:
        print(f"Blend does NOT beat the best single model on the untouched test season "
              f"({blend['rps']} vs {best_single['rps']}) -- Phase 1's validation-season "
              f"signal did not survive to a genuinely held-out season. Do not promote.")


if __name__ == "__main__":
    main()
