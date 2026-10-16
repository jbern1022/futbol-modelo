"""
Does the live pooled team-props model (CORNERS, SOT) transfer to a new league,
and does adding that league to the training pool hurt the existing ones?

Decision rules R1-R3 are pre-registered in docs/EXPERIMENT_REGISTRY.md
("Pre-registration, Bundesliga CORNERS and SOT props"), committed before
this script produced any result. Read-only: one SELECT, no writes.

Mirrors generate_slate.fit_props_model: same rows (n_prior >= 5, every
feature present), same LightGBM hyperparameters, same 5-fold out-of-fold
isotonic calibrators per line. The model has no league feature.

  Test A (out-of-league): train on existing-league rows kicking off before
          the holdout season, score the new league's holdout season.
  Test B (non-inferiority): train on existing-league rows before 2025-08-01
          with and without the new league's earlier rows, score the existing
          leagues' later rows.

    python scripts/experiment_props_new_league.py --league BUNDESLIGA --market CORNERS
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold

from generate_slate import PROPS_MARKETS, lgb

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Copy of the dict in generate_slate.fit_props_model (it is not exported).
# Keep in sync: the experiment is only meaningful for the live settings.
HYPERPARAMS = {"objective": "poisson", "n_estimators": 300, "learning_rate": 0.03,
               "num_leaves": 20, "min_child_samples": 30, "subsample": 0.8,
               "colsample_bytree": 0.8}
EXISTING = ("EPL", "SERIE_A", "LA_LIGA", "MLS")
B_CUTOFF = "2025-08-01"
N_BOOT = 2000


def load(cur, market: str, leagues: tuple[str, ...]) -> pd.DataFrame:
    spec = PROPS_MARKETS[market]
    feats = spec["features"]
    cols = ", ".join(f"f.{c}" for c in feats)
    cur.execute(
        f"""SELECT {cols}, tms.{spec['target_col']} AS y, l.code AS league, s.label AS season,
                   f.match_id, f.kickoff_utc
            FROM futbol.team_match_features f
            JOIN futbol.matches m ON m.match_id = f.match_id
            JOIN futbol.seasons s ON s.season_id = m.season_id
            JOIN futbol.leagues l ON l.league_id = s.league_id
            JOIN futbol.team_match_stats tms
              ON tms.match_id = f.match_id AND tms.team_id = f.team_id
            WHERE l.code = ANY(%s) AND tms.{spec['target_col']} IS NOT NULL
              AND f.n_prior >= 5""", (list(leagues),))
    df = pd.DataFrame(cur.fetchall(), columns=feats + ["y", "league", "season", "match_id", "kickoff"])
    for c in feats + ["y"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=feats + ["y"]).copy()
    df["is_home"] = df["is_home"].astype(int)
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    return df.reset_index(drop=True)


def fit(train: pd.DataFrame, feats: list[str], lines: list[float]):
    """(model, {line: isotonic}) exactly as the live pipeline builds them."""
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    oof = np.zeros(len(train))
    X, y = train[feats], train["y"]
    for tr, va in kf.split(train):
        m = lgb.LGBMRegressor(verbose=-1, **HYPERPARAMS).fit(X.iloc[tr], y.iloc[tr])
        oof[va] = np.maximum(m.predict(X.iloc[va]), 0.05)
    cals = {}
    for line in lines:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        iso.fit(1 - poisson.cdf(np.floor(line), oof), (y.values > line).astype(int))
        cals[line] = iso
    model = lgb.LGBMRegressor(verbose=-1, **HYPERPARAMS).fit(X, y)
    return model, cals


def predict_mu(model, df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    return np.maximum(model.predict(df[feats]), 0.05)


def ll_rows(y: np.ndarray, mu) -> np.ndarray:
    """Per-row Poisson negative log-likelihood."""
    return -poisson.logpmf(y.astype(int), np.clip(mu, 1e-6, None))


def boot_ci(diff: np.ndarray, match_ids: np.ndarray, seed: int = 0) -> tuple[float, float, float]:
    """Mean and 95% percentile interval, resampling whole matches."""
    d = pd.DataFrame({"m": match_ids, "d": diff}).groupby("m")["d"].agg(["sum", "count"])
    sums, counts = d["sum"].to_numpy(), d["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(N_BOOT, len(d)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)


def test_a(df: pd.DataFrame, league: str, market: str, holdout: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    new = df[df.league == league]
    test = new[new.season == holdout]
    cutoff = test.kickoff.min()
    train = df[df.league.isin(EXISTING) & (df.kickoff < cutoff)]
    hist = new[new.kickoff < cutoff]
    model, cals = fit(train, feats, lines)
    mu = predict_mu(model, test, feats)
    y = test["y"].to_numpy()

    out = {"holdout": holdout, "n_test": len(test), "n_train": len(train), "n_hist": len(hist),
           "mean_pred": float(mu.mean()), "mean_actual": float(y.mean()),
           "own_mean": float(hist["y"].mean()), "pool_mean": float(train["y"].mean())}
    ll_model = ll_rows(y, mu)
    ll_own = ll_rows(y, np.full(len(y), out["own_mean"]))
    ll_pool = ll_rows(y, np.full(len(y), out["pool_mean"]))
    out["ll_model"], out["ll_own"], out["ll_pool"] = ll_model.mean(), ll_own.mean(), ll_pool.mean()
    out["gain_vs_own"] = boot_ci(ll_own - ll_model, test["match_id"].to_numpy())
    out["gain_vs_pool"] = boot_ci(ll_pool - ll_model, test["match_id"].to_numpy())

    out["lines"] = {}
    for line in lines:
        raw = 1 - poisson.cdf(np.floor(line), mu)
        cal = cals[line].predict(raw)
        actual = (y > line).astype(int)

        def qgap(p):
            try:
                b = pd.qcut(p, q=4, duplicates="drop")
            except ValueError:
                return float("nan")
            g = pd.DataFrame({"b": b, "s": p, "a": actual}).groupby("b", observed=True).agg(
                s=("s", "mean"), a=("a", "mean"))
            return float((g["a"] - g["s"]).abs().mean())

        bands = []
        edges = np.arange(0, 1.0001, 0.1)
        band = pd.cut(cal, edges, include_lowest=True)
        g = pd.DataFrame({"b": band, "s": cal, "a": actual}).groupby("b", observed=True).agg(
            n=("a", "size"), s=("s", "mean"), a=("a", "mean"))
        for iv, r in g.iterrows():
            bands.append((f"{iv.left:.1f}-{iv.right:.1f}", int(r.n), float(r.s), float(r.a)))
        out["lines"][line] = {"raw_gap": qgap(raw), "cal_gap": qgap(cal), "bands": bands,
                              "base_rate": float(actual.mean())}
    return out


def test_b(df: pd.DataFrame, league: str, market: str) -> dict:
    spec = PROPS_MARKETS[market]
    feats, lines = spec["features"], spec["lines"]
    cutoff = pd.Timestamp(B_CUTOFF, tz="UTC")
    base = df[df.league.isin(EXISTING) & (df.kickoff < cutoff)]
    extra = df[(df.league == league) & (df.kickoff < cutoff)]
    test = df[df.league.isin(EXISTING) & (df.kickoff >= cutoff)]
    m_without, _ = fit(base, feats, lines)
    m_with, _ = fit(pd.concat([base, extra], ignore_index=True), feats, lines)
    y = test["y"].to_numpy()
    ll_without = ll_rows(y, predict_mu(m_without, test, feats))
    ll_with = ll_rows(y, predict_mu(m_with, test, feats))
    diff = ll_with - ll_without  # positive = adding the league hurts
    res = {"n_base": len(base), "n_extra": len(extra), "n_test": len(test),
           "pooled": boot_ci(diff, test["match_id"].to_numpy())}
    res["by_league"] = {}
    for lg in sorted(test.league.unique()):
        mask = (test.league == lg).to_numpy()
        res["by_league"][lg] = (int(mask.sum()),) + boot_ci(diff[mask], test["match_id"].to_numpy()[mask])
    return res


def verdict(a_primary: dict, a_second: dict, b: dict) -> dict:
    r1 = (a_primary["gain_vs_own"][1] > 0) and (a_second["gain_vs_own"][0] > 0)
    r2 = True
    for line, d in a_primary["lines"].items():
        if not (d["cal_gap"] <= 0.05):
            r2 = False
        for _, n, s, a in d["bands"]:
            if n >= 100 and abs(a - s) > 0.07:
                r2 = False
    r3 = b["pooled"][2] < 0.001
    return {"R1": r1, "R2": r2, "R3": r3, "promote": r1 and r2 and r3}


def report(market: str, league: str, a1: dict, a2: dict, b: dict) -> None:
    print(f"\n===== {league} {market} =====")
    for a in (a1, a2):
        print(f"\nTest A, holdout {a['holdout']}: train {a['n_train']} existing-league rows, "
              f"{a['n_hist']} own-history rows, test {a['n_test']}")
        print(f"  mean predicted {a['mean_pred']:.3f}  mean actual {a['mean_actual']:.3f}  "
              f"own-history mean {a['own_mean']:.3f}  pool mean {a['pool_mean']:.3f}")
        print(f"  Poisson log loss: model {a['ll_model']:.4f}  own-mean {a['ll_own']:.4f}  "
              f"pool-mean {a['ll_pool']:.4f}")
        g = a["gain_vs_own"]
        print(f"  gain vs own-mean (positive = model better): {g[0]:+.4f}  "
              f"95% [{g[1]:+.4f}, {g[2]:+.4f}]")
        g = a["gain_vs_pool"]
        print(f"  gain vs pool-mean:                          {g[0]:+.4f}  95% [{g[1]:+.4f}, {g[2]:+.4f}]")
    print(f"\nCalibration, holdout {a1['holdout']} (live-style calibrators):")
    for line, d in a1["lines"].items():
        print(f"  Over {line}: base rate {d['base_rate']:.3f}  raw quartile gap {d['raw_gap']:.3f}  "
              f"calibrated quartile gap {d['cal_gap']:.3f}")
        for name, n, s, act in d["bands"]:
            flag = "  <-- >0.07" if n >= 100 and abs(act - s) > 0.07 else ""
            print(f"      band {name}: n={n:4d} stated {s:.3f} realized {act:.3f} gap {act - s:+.3f}{flag}")
    print(f"\nTest B (adding {league} to the pool): train {b['n_base']} (+{b['n_extra']}), "
          f"test {b['n_test']} existing-league rows")
    m, lo, hi = b["pooled"]
    print(f"  pooled log-loss change (with minus without; positive = hurts): {m:+.5f}  95% [{lo:+.5f}, {hi:+.5f}]")
    for lg, (n, m, lo, hi) in b["by_league"].items():
        print(f"    {lg:8s} n={n:5d} {m:+.5f}  [{lo:+.5f}, {hi:+.5f}]")
    v = verdict(a1, a2, b)
    print(f"\nVerdict: R1 skill {'PASS' if v['R1'] else 'FAIL'} | R2 calibration {'PASS' if v['R2'] else 'FAIL'} | "
          f"R3 non-inferiority {'PASS' if v['R3'] else 'FAIL'} -> "
          f"{'PROMOTE' if v['promote'] else 'DO NOT PROMOTE'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["BUNDESLIGA"])
    ap.add_argument("--market", required=True, choices=["CORNERS", "SOT"])
    ap.add_argument("--holdouts", nargs=2, default=["2025-26", "2024-25"], metavar=("PRIMARY", "SECOND"))
    args = ap.parse_args()
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(DSN)
    conn.set_session(readonly=True)
    cur = conn.cursor()
    df = load(cur, args.market, EXISTING + (args.league,))
    conn.close()
    print(f"{len(df)} rows: " + ", ".join(f"{k} {v}" for k, v in df.league.value_counts().items()))

    a1 = test_a(df, args.league, args.market, args.holdouts[0])
    a2 = test_a(df, args.league, args.market, args.holdouts[1])
    b = test_b(df, args.league, args.market)
    report(args.market, args.league, a1, a2, b)


if __name__ == "__main__":
    main()
