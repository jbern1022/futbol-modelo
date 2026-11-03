"""
Controlled-scenario validation of src/evaluation/projected_failure.py (Todoist 6hm2JMm4XrQJpJcf).
SIMULATION ONLY: no database, no real outcomes.

Approved scenarios (owner, 2026-10-29): well-calibrated, deteriorating, recovering, sparse data.
Criteria are fixed here BEFORE the first run and are not tuned to the output:

  V1 well-calibrated  Among series whose band passes at N (|gap| <= 3 pts), the share with a
                      would_warn status at ANY checkpoint is <= 5%.
  V2 deteriorating    Gap drifts linearly from 0 to -10 pts over N. Share that reach would_warn
                      by n = 1,200 is >= 80%.
  V3 recovering       Gap is -6 pts for the first 400 predictions then 0 (final gap -1.9 pts,
                      band passes). Report the share ever warned (early noise) and the share
                      warned at the last checkpoint; require last-checkpoint warned <= 5%.
  V4 sparse           n = 350 only, 25 matches repeated thin data is simulated as 350 predictions
                      from few distinct matches (size 14). Require that no calibrated series is
                      would_warn more than 5% of the time (unstable is acceptable and expected).
  V5 labelling        Report how often 'unstable' is returned in V1 and V4 (not gated).

Dependence: 5 predictions per match, within-match correlation rho = 0.12 (ledger-observed for
props, docs/PROJECTED_FAILURE_ESTIMATOR_OPTIONS.md) unless --rho says otherwise.

    python scripts/validate_projected_failure.py --reps 150 --sims 600     # default, ~minutes
    python scripts/validate_projected_failure.py --reps 20 --sims 200       # smoke
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from evaluation import projected_failure as pf  # noqa: E402

N, C, PBAR, TOL = pf.MATURE_N, 5, 0.65, pf.TOL_FINAL


def make_series(rng, gap_fn, rho, n=N, size=C):
    """(probs, hits, match_ids) with stated probs ~ U(0.60, 0.70) per match and within-match rho."""
    k = n // size
    p_m = rng.uniform(0.60, 0.70, k)
    p = np.repeat(p_m, size)
    mid = np.repeat(np.arange(k), size)
    pos = np.arange(k * size)
    theta = np.clip(p + gap_fn(pos), 1e-4, 1 - 1e-4)
    if rho > 0:
        s = 1.0 / rho - 1.0
        th_m = rng.beta(theta.reshape(k, size).mean(1) * s, (1 - theta.reshape(k, size).mean(1)) * s)
        theta = np.repeat(th_m, size) + (theta - np.repeat(theta.reshape(k, size).mean(1), size))
        theta = np.clip(theta, 0.0, 1.0)
    y = (rng.random(len(p)) < theta).astype(int)
    return p, y, mid


def passes(p, y, tol=TOL):
    return abs(y.mean() - p.mean()) <= tol + 1e-12


def run_scenario(name, gap_fn, reps, sims, rho, seed, n=N, size=C):
    rng = np.random.default_rng(seed)
    out = []
    for r in range(reps):
        p, y, mid = make_series(rng, gap_fn, rho, n=n, size=size)
        use = min(len(p), 1200)
        seq = pf.sequence_status(p[:use], y[:use], mid[:use], sims=sims, seed=seed + r)
        out.append((passes(p, y), seq))
    return out


def summarise(rows):
    n = len(rows)
    ever = np.mean([s.ever_warned for _, s in rows])
    last = np.mean([s.currently_warned for _, s in rows])
    unst = np.mean([s.first_unstable_n is not None for _, s in rows])
    pas = np.array([ok for ok, _ in rows])
    ever_given_pass = np.mean([s.ever_warned for ok, s in rows if ok]) if pas.any() else float("nan")
    first = [s.first_warn_n for _, s in rows if s.first_warn_n]
    ever_given_fail = np.mean([s.ever_warned for ok, s in rows if not ok]) if (~pas).any() else float("nan")
    return dict(ever_given_fail=ever_given_fail, n=n, pass_rate=pas.mean(), ever=ever, last=last, unstable=unst,
                ever_given_pass=ever_given_pass,
                median_first=float(np.median(first)) if first else float("nan"))


def pct(x):
    return "  n/a" if x != x else f"{100 * x:5.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=150)
    ap.add_argument("--sims", type=int, default=600)
    ap.add_argument("--rho", type=float, default=0.12)
    ap.add_argument("--seed", type=int, default=20261102)
    a = ap.parse_args()
    t0 = time.time()
    print(f"method {pf.METHOD_VERSION}; reps={a.reps} sims={a.sims} rho={a.rho} seed={a.seed}; "
          f"alpha={pf.ALPHA}; checkpoints 350..1200 step 50\n")

    scen = {
        "V1 well-calibrated": (lambda pos: np.zeros(len(pos)), N, C),
        "V2 deteriorating (0 -> -10 pts)": (lambda pos: -0.10 * pos / N, N, C),
        "V3 recovering (-6 pts for 400, then 0)": (lambda pos: np.where(pos < 400, -0.06, 0.0), N, C),
        "V4 sparse (350 preds, 14 per match)": (lambda pos: np.zeros(len(pos)), 350, 14),
    }
    res = {}
    print("| scenario | series passing at N | ever would_warn | would_warn at last checkpoint "
          "| ever 'unstable' | ever_warn given pass | median n at first warn |")
    print("|---|---|---|---|---|---|---|")
    for i, (name, (fn, n, size)) in enumerate(scen.items()):
        rows = run_scenario(name, fn, a.reps, a.sims, a.rho, a.seed + 1000 * i, n=n, size=size)
        s = summarise(rows)
        res[name] = s
        print(f"| {name} | {pct(s['pass_rate'])} | {pct(s['ever'])} | {pct(s['last'])} "
              f"| {pct(s['unstable'])} | {pct(s['ever_given_pass'])} | {s['median_first']:.0f} |")

    v1 = res["V1 well-calibrated"]
    v2 = res["V2 deteriorating (0 -> -10 pts)"]
    v3 = res["V3 recovering (-6 pts for 400, then 0)"]
    v4 = res["V4 sparse (350 preds, 14 per match)"]
    print("\nCriteria (fixed before the first run):")
    print(f"- V1 false alarms among passing series <= 5%: {pct(v1['ever_given_pass'])} -> "
          f"{'MEETS' if v1['ever_given_pass'] <= 0.05 else 'FAILS'}")
    print(f"- V2 deteriorating flagged by n=1200 >= 80%: {pct(v2['ever'])} -> "
          f"{'MEETS' if v2['ever'] >= 0.80 else 'FAILS'}  "
          f"(reported after the first run, not gated: among series that really fail at N, "
          f"{pct(v2['ever_given_fail'])} flagged)")
    print(f"- V3 recovering, warned at last checkpoint <= 5%: {pct(v3['last'])} -> "
          f"{'MEETS' if v3['last'] <= 0.05 else 'FAILS'}  (ever warned: {pct(v3['ever'])})")
    print(f"- V4 sparse, calibrated series would_warn <= 5%: {pct(v4['ever'])} -> "
          f"{'MEETS' if v4['ever'] <= 0.05 else 'FAILS'}  (unstable: {pct(v4['unstable'])})")
    print(f"\nelapsed {time.time() - t0:.0f}s. Pass/fail here is evidence for review, "
          "not authorization to enable the warning (pf.WARNING_ENABLED stays False).")


if __name__ == "__main__":
    main()
