"""
Operating characteristics of candidate projected-failure estimators (Todoist 6hm2JMm4XrQJpJcf).
SIMULATION ONLY: no database, no real outcomes. ADR-020 restated the goal as calibration: at
N = 1,250 live graded predictions a band's realized rate should sit within +/-TOL of its stated
probability. The projected-failure rule asks, from n >= 350 predictions in, how likely that is;
below 5% the cohort is labelled PROJECTED FAILURE (mandatory review, never a deletion).

This script does NOT choose a method (ADR-017: the method is selected by the owner and
independently reviewed). It measures how each candidate behaves.

Criteria fixed BEFORE the first run (docs/PROJECTED_FAILURE_ESTIMATOR_OPTIONS.md):
  C1 false alarms: among series whose band WOULD pass at N (truly within tolerance), the share
     flagged at ANY checkpoint (repeated monitoring) is <= 5%, at the ledger-observed dependence
     (rho = 0.12 within match, 5 predictions per match).
  C2 power: among series whose true rate is 5 points off, >= 80% are flagged by n = 1,200.
  Reported, not gated: precision of a flag, median n at first flag, behaviour at rho = 0 / 0.25,
  and the true-gap sweep.

Estimators (all answer: P(final realized rate within TOL of stated | n so far)):
  plugin     binomial at the observed rate k/n (ignores uncertainty in the rate)
  betabin    Beta-binomial, flat prior (Bayesian, rate uncertainty, independence assumed)
  betabin_c  Beta-binomial, prior centred on the stated probability, strength 50 predictions
  cluster    normal approximation, variance inflated by a cluster-robust design effect

    python scripts/experiment_projected_failure_estimators.py            # full run, markdown
    python scripts/experiment_projected_failure_estimators.py --series 400 --rhos 0.12   # quick
"""
from __future__ import annotations

import argparse

import numpy as np
from scipy.stats import betabinom, binom, norm

N, C, PBAR, TOL, ALPHA = 1250, 5, 0.65, 0.03, 0.05
CHECKPOINTS = list(range(350, 1201, 50))
ESTIMATORS = ("plugin", "betabin", "betabin_c", "cluster")


def simulate(S: int, theta: float, rho: float, rng) -> np.ndarray:
    """(S, N) hits; N/C matches, C predictions each, intraclass correlation rho."""
    k = N // C
    if rho <= 0:
        th = np.full((S, k), theta)
    else:
        s = 1.0 / rho - 1.0
        th = rng.beta(theta * s, (1 - theta) * s, size=(S, k))
    y = (rng.uniform(size=(S, k, C)) < th[:, :, None]).astype(np.int8)
    return y.reshape(S, N)


def bounds(k: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    lo = np.ceil(N * (PBAR - TOL) - k - 1e-9)
    hi = np.floor(N * (PBAR + TOL) - k + 1e-9)
    return lo, hi


def p_success(est: str, y: np.ndarray, n: int, kappa: float = 50.0) -> np.ndarray:
    k = y[:, :n].sum(axis=1).astype(float)
    m = N - n
    lo, hi = bounds(k, n)
    if est == "plugin":
        th = np.clip(k / n, 1e-6, 1 - 1e-6)
        return np.clip(binom.cdf(hi, m, th) - binom.cdf(lo - 1, m, th), 0, 1)
    if est == "betabin":
        a, b = 1 + k, 1 + n - k
        return np.clip(betabinom.cdf(hi, m, a, b) - betabinom.cdf(lo - 1, m, a, b), 0, 1)
    if est == "betabin_c":
        a, b = kappa * PBAR + k, kappa * (1 - PBAR) + n - k
        return np.clip(betabinom.cdf(hi, m, a, b) - betabinom.cdf(lo - 1, m, a, b), 0, 1)
    if est == "cluster":
        th = np.clip(k / n, 1e-6, 1 - 1e-6)
        means = y[:, :n].reshape(len(y), n // C, C).mean(axis=2)
        deff = np.clip(means.var(axis=1, ddof=1) / (th * (1 - th) / C), 1.0, float(C))
        v1 = th * (1 - th) * deff
        mean = (k + m * th) / N
        sd = np.sqrt((m * v1 + m * m * v1 / n) / N**2)
        return norm.cdf((PBAR + TOL - mean) / sd) - norm.cdf((PBAR - TOL - mean) / sd)
    raise ValueError(est)


def run(S: int, rho: float, delta: float, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    y = simulate(S, PBAR + delta, rho, rng)
    final = y.sum(axis=1) / N
    passes = np.abs(final - PBAR) <= TOL + 1e-12
    out = {"passes": float(passes.mean())}
    for est in ESTIMATORS:
        first = np.full(S, np.inf)
        for n in CHECKPOINTS:
            flag = p_success(est, y, n) < ALPHA
            first = np.where(flag & np.isinf(first), n, first)
        flagged = np.isfinite(first)
        out[est] = {
            "any": float(flagged.mean()),
            "false_flag_given_pass": float(flagged[passes].mean()) if passes.any() else float("nan"),
            "flag_given_fail": float(flagged[~passes].mean()) if (~passes).any() else float("nan"),
            "precision": float((~passes)[flagged].mean()) if flagged.any() else float("nan"),
            "median_n": float(np.median(first[flagged])) if flagged.any() else float("nan"),
        }
    return out


def fmt(x: float) -> str:
    return "  n/a" if x != x else f"{100 * x:5.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", type=int, default=4000)
    ap.add_argument("--rhos", type=float, nargs="+", default=[0.0, 0.05, 0.12, 0.25])
    ap.add_argument("--deltas", type=float, nargs="+", default=[0.0, 0.02, 0.03, 0.05, 0.08])
    ap.add_argument("--seed", type=int, default=20261029)
    a = ap.parse_args()
    print(f"N={N} cluster={C} stated={PBAR} tol=+/-{TOL} flag if P(success) < {ALPHA}; "
          f"checkpoints {CHECKPOINTS[0]}..{CHECKPOINTS[-1]} step 50; {a.series} series per cell\n")
    for rho in a.rhos:
        print(f"### within-match correlation rho = {rho}")
        print("| true gap | band passes | estimator | flagged (any) | false flag | power "
              "| flag precision | median n at flag |")
        print("|---|---|---|---|---|---|---|---|")
        for d in a.deltas:
            r = run(a.series, rho, -d, a.seed)
            for est in ESTIMATORS:
                e = r[est]
                print(f"| {100 * d:.0f} pts | {100 * r['passes']:.0f}% | {est} | {fmt(e['any'])}% "
                      f"| {fmt(e['false_flag_given_pass'])}% | {fmt(e['flag_given_fail'])}% "
                      f"| {fmt(e['precision'])}% | {e['median_n']:.0f} |")
        print()


if __name__ == "__main__":
    main()
