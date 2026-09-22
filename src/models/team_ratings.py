"""
Bootstrap confidence intervals on Dixon-Coles' fitted attack/defence
ratings (Todoist: "Uncertainty intervals on team attack/defence
ratings"). Error bars are the visual language of "we know what we
don't know" -- but there was nowhere to attach them to: no
team-strength display existed anywhere on the site, and DixonColes.rates()
only ever derives lam/mu for a specific fixture pairing, never exposes
raw per-team atk/dfn on their own. This is the missing piece: expose
the fitted params, then wrap them with real uncertainty.

Bootstrap, not the optimizer's Hessian: fit() uses SLSQP with an
equality constraint (mean attack = 0 for identifiability). The
standard inverse-Hessian standard-error formula assumes an
UNCONSTRAINED optimum -- applying it naively here would understate
uncertainty without correcting for the constraint's effect on the
covariance structure, real extra statistical work with its own
failure modes. A nonparametric case-resampling bootstrap sidesteps
that entirely: refit the whole model on resampled data, many times,
and just look at the empirical spread of the fitted values. Slower
(each replicate is a full refit) but honest, and consistent with how
every other calibration decision in this project already prefers
empirical intervals over analytical approximations (see the isotonic
OOF calibration in scripts/generate_slate.py's fit_props_model).

Usage:
    from models.dixon_coles import DixonColes
    from models.team_ratings import bootstrap_team_ratings

    result = bootstrap_team_ratings(df, xi=0.0015, reg=0.0)
    # result["Arsenal"] -> {"atk": 0.31, "atk_ci_low": 0.18, "atk_ci_high": 0.44, ...}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dixon_coles import DixonColes


def _team_params(model: DixonColes) -> dict[str, tuple[float, float]]:
    """{team: (atk, dfn)} from an already-fitted model."""
    n = len(model.teams)
    atk, dfn = model.params[:n], model.params[n:2 * n]
    return {t: (float(atk[i]), float(dfn[i])) for t, i in model._idx.items()}


def bootstrap_team_ratings(
    df: pd.DataFrame, *, xi: float, reg: float = 0.0,
    n_boot: int = 200, ci: float = 0.90, seed: int = 42,
) -> dict[str, dict[str, float]]:
    """
    Case-resampling bootstrap over match rows (df: date, home, away, hg,
    ag -- same shape DixonColes.fit() takes). Returns, per team, the
    point estimate from fitting on the REAL (unresampled) data plus
    percentile CI bounds from n_boot refits on resampled data.

    A team that drops out of a given resample entirely (possible for a
    team with very few matches, unlikely for a full-season regular)
    just contributes no sample to that team's CI for that replicate --
    handled by tracking per-team sample lists independently rather than
    assuming every replicate covers every team.
    """
    real_model = DixonColes(xi=xi).fit(df, reg=reg)
    point_estimates = _team_params(real_model)

    rng = np.random.default_rng(seed)
    n = len(df)
    atk_samples: dict[str, list[float]] = {t: [] for t in real_model.teams}
    dfn_samples: dict[str, list[float]] = {t: [] for t in real_model.teams}

    for _ in range(n_boot):
        resample_idx = rng.integers(0, n, size=n)
        resampled = df.iloc[resample_idx].reset_index(drop=True)
        try:
            boot_model = DixonColes(xi=xi).fit(resampled, reg=reg)
        except Exception:
            # A pathological resample (e.g. SLSQP fails to converge on
            # a degenerate draw) contributes nothing rather than
            # crashing the whole bootstrap -- rare, but a real
            # possibility with case resampling on a small league.
            continue
        for team, (atk, dfn) in _team_params(boot_model).items():
            if team in atk_samples:
                atk_samples[team].append(atk)
                dfn_samples[team].append(dfn)

    lo_pct = (1 - ci) / 2 * 100
    hi_pct = (1 + ci) / 2 * 100

    out: dict[str, dict[str, float]] = {}
    for team in real_model.teams:
        atk_point, dfn_point = point_estimates[team]
        a_samples, d_samples = atk_samples[team], dfn_samples[team]
        out[team] = {
            "atk": atk_point,
            "atk_ci_low": float(np.percentile(a_samples, lo_pct)) if a_samples else atk_point,
            "atk_ci_high": float(np.percentile(a_samples, hi_pct)) if a_samples else atk_point,
            "dfn": dfn_point,
            "dfn_ci_low": float(np.percentile(d_samples, lo_pct)) if d_samples else dfn_point,
            "dfn_ci_high": float(np.percentile(d_samples, hi_pct)) if d_samples else dfn_point,
            "n_boot_samples": len(a_samples),
        }
    return out
