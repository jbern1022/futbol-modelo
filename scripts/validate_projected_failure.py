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

Added 2026-11-02, criteria written BEFORE these were run (the V1-V4 criteria above are unchanged):

  V3b recovering      Among V3 series that PASS at N, the share warned at the last checkpoint is
                      <= 5%. (V3 as first written also counted series that really fail at N, which
                      should be warned; V3b is the question that was meant. V3 stays in the table.)
  V5 matchweek        Calibrated on average, but every block of 10 matches (50 predictions) shares
                      an additive shift ~ N(0, 4 pts). Among series that pass at N, the share ever
                      warned is <= 5% when whole matchweeks are the resampling unit. The same
                      series resampled by match are reported alongside, not gated.
  P2/P3 persistence   Rule "warn only after k = 2 (or 3) consecutive would_warn checkpoints".
                      k is acceptable only if V1 false alarms among passing series stay <= 5% AND
                      among V2 series that really fail at N at least 80% still reach a persistent
                      warning by n = 1,200. Reported for k = 1, 2, 3; nothing is tuned beyond that.

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


WEEK_MATCHES = 10


def make_series(rng, gap_fn, rho, n=N, size=C, week_sd=0.0):
    """(probs, hits, match_ids, week_ids): stated probs ~ U(0.60, 0.70) per match, within-match rho,
    and optionally a shared additive shift per block of WEEK_MATCHES matches (sd week_sd)."""
    k = n // size
    p_m = rng.uniform(0.60, 0.70, k)
    p = np.repeat(p_m, size)
    mid = np.repeat(np.arange(k), size)
    wk = mid // WEEK_MATCHES
    pos = np.arange(k * size)
    shift = rng.normal(0.0, week_sd, wk.max() + 1)[wk] if week_sd > 0 else 0.0
    theta = np.clip(p + gap_fn(pos) + shift, 1e-4, 1 - 1e-4)
    if rho > 0:
        s = 1.0 / rho - 1.0
        th_m = rng.beta(theta.reshape(k, size).mean(1) * s, (1 - theta.reshape(k, size).mean(1)) * s)
        theta = np.repeat(th_m, size) + (theta - np.repeat(theta.reshape(k, size).mean(1), size))
        theta = np.clip(theta, 0.0, 1.0)
    y = (rng.random(len(p)) < theta).astype(int)
    return p, y, mid, wk


def passes(p, y, tol=TOL):
    return abs(y.mean() - p.mean()) <= tol + 1e-12


def run_scenario(name, gap_fn, reps, sims, rho, seed, n=N, size=C, week_sd=0.0, by_week=False):
    rng = np.random.default_rng(seed)
    out = []
    for r in range(reps):
        p, y, mid, wk = make_series(rng, gap_fn, rho, n=n, size=size, week_sd=week_sd)
        use = min(len(p), 1200)
        seq = pf.sequence_status(p[:use], y[:use], mid[:use], unit_ids=wk[:use] if by_week else None,
                                 sims=sims, seed=seed + r)
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
    last_pass = np.mean([s.currently_warned for ok, s in rows if ok]) if pas.any() else float("nan")
    last_fail = np.mean([s.currently_warned for ok, s in rows if not ok]) if (~pas).any() else float("nan")
    persist = {}
    for k in (1, 2, 3):
        hit = [pf.persistent_warn_n(s, k) is not None for _, s in rows]
        persist[k] = (
            float(np.mean(hit)),
            float(np.mean([h for h, (ok, _) in zip(hit, rows) if ok])) if pas.any() else float("nan"),
            float(np.mean([h for h, (ok, _) in zip(hit, rows) if not ok])) if (~pas).any() else float("nan"),
        )
    return dict(last_given_pass=last_pass, last_given_fail=last_fail, persist=persist,
                ever_given_fail=ever_given_fail, n=n, pass_rate=pas.mean(), ever=ever, last=last, unstable=unst,
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
    ap.add_argument("--only", choices=["base", "week"], default=None,
                    help="base = V1-V4 + V3b + persistence; week = V5 only (split to fit time limits)")
    a = ap.parse_args()
    t0 = time.time()
    print(f"method {pf.METHOD_VERSION}; reps={a.reps} sims={a.sims} rho={a.rho} seed={a.seed}; "
          f"alpha={pf.ALPHA}; checkpoints 350..1200 step 50\n")
    if a.only in (None, "base"):
        run_base(a)
    if a.only in (None, "week"):
        run_week(a)
    print(f"\nelapsed {time.time() - t0:.0f}s. Pass/fail here is evidence for review, "
          "not authorization to enable the warning (pf.WARNING_ENABLED stays False).")


def run_base(a):
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
    print("\nPersistence rule: persistent warning by n=1,200 for k consecutive would_warn checkpoints")
    print("| scenario | k | any series | among series passing at N | among series failing at N |")
    print("|---|---|---|---|---|")
    for name, s in (("V1", v1), ("V2", v2), ("V3", v3)):
        for k, (anyk, pas, fail) in s["persist"].items():
            print(f"| {name} | {k} | {pct(anyk)} | {pct(pas)} | {pct(fail)} |")
    print("\nCriteria:")
    print(f"- V3b recovering, passing-at-N series warned at the last checkpoint <= 5%: "
          f"{pct(v3['last_given_pass'])} -> {'MEETS' if v3['last_given_pass'] <= 0.05 else 'FAILS'}"
          f"  (failing-at-N series warned at last checkpoint: {pct(v3['last_given_fail'])})")
    for k in (2, 3):
        fa = v1["persist"][k][1]
        pw = v2["persist"][k][2]
        ok = fa <= 0.05 and pw >= 0.80
        print(f"- P{k} persistence k={k}: V1 false alarm among passing {pct(fa)} (<=5%), V2 power among "
              f"failing {pct(pw)} (>=80%) -> {'MEETS' if ok else 'FAILS'}")


def run_week(a):
    print("\nV5 matchweek effect: calibrated on average, shared shift per 10-match block ~ N(0, 4 pts)")
    print("| resampling unit | series passing at N | ever would_warn | ever_warn given pass "
          "| ever 'unstable' | median n at first warn |")
    print("|---|---|---|---|---|---|")
    out = {}
    for label, by_week in (("matchweek", True), ("match", False)):
        rows = run_scenario("V5", lambda pos: np.zeros(len(pos)), a.reps, a.sims, a.rho, a.seed + 9000,
                            week_sd=0.04, by_week=by_week)
        s = summarise(rows)
        out[label] = s
        print(f"| {label} | {pct(s['pass_rate'])} | {pct(s['ever'])} | {pct(s['ever_given_pass'])} "
              f"| {pct(s['unstable'])} | {s['median_first']:.0f} |")
    w = out["matchweek"]["ever_given_pass"]
    print(f"\n- V5 matchweek resampling, false alarms among passing series <= 5%: {pct(w)} -> "
          f"{'MEETS' if w <= 0.05 else 'FAILS'}  (by match, not gated: {pct(out['match']['ever_given_pass'])})")


if __name__ == "__main__":
    main()
