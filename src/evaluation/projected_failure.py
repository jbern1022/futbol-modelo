"""
Projected-failure estimator, first development method (owner-approved 2026-10-29,
Todoist 6hm2JMm4XrQJpJcf; Notion decision "Futbol Modelo - Calibration tolerance decision").

STATUS: development. This is NOT a validated estimator and the warning it can produce is
DISABLED (WARNING_ENABLED is False). Nothing in the site, a job or a view calls this module.
Enabling the warning needs the controlled-scenario validation to pass AND independent
statistical review (ADR-017 / ADR-020). See docs/PROJECTED_FAILURE_ESTIMATOR_SPEC.md.

Question answered, for ONE cohort (league + market + model version, live graded predictions
only, in time order) and ONE fixed 10-point probability band:

    Given the n results so far, how likely is it that, at N = 1,250 predictions in the band,
    |observed hit rate - mean stated probability| <= tolerance (+/-3 points)?

Method (version METHOD_VERSION), the six approved choices:

 1. Target: calibration at N = MATURE_N, tolerance TOL_FINAL. (Not "reach 80% accuracy".)
 2. Bands: the same fixed deciles as evidence.py / the v_calibration view, declared before
    evaluation. The gap compares the observed hit frequency with the MEAN stated probability
    of the band's predictions (not the band midpoint).
 3. Dependence: predictions are grouped by match_id and resampled as whole matches, so
    correlated props on one match are never treated as independent.
 4. Simulation: observed results are retained. The remaining N - n predictions are simulated
    by (a) drawing a "world" as a Bayesian bootstrap over the observed matches (Dirichlet
    weights; this carries the uncertainty about the band's true calibration gap) and (b)
    drawing future matches from that world. Each match keeps its own stated probabilities and
    hits (so cluster sizes, probability mix and within-match dependence are preserved).
    Assumption stated plainly: future fixtures and stated probabilities look like the
    observed ones (exchangeable matches). Drift is handled only by the sensitivity variants.
 5. Cadence: formal status is evaluated at n = 350 and at every additional 50 predictions in
    the band; between checkpoints the status does not change. sequence_status() replays every
    checkpoint so repeated-monitoring behaviour is visible.
 6. Uncertainty is shown, not hidden: the estimate is computed under several reasonable
    assumption variants (VARIANTS). If they straddle the warning line the projection is
    labelled UNSTABLE rather than flagged or cleared.

Projected failure is a review trigger, not a confirmed failure and never an automatic
replacement. Pure functions over arrays; no database, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .evidence import MATURE_N, MIN_BAND_N, TOL_FINAL, _band

METHOD_VERSION = "pf-bayesboot-1"
BANDS_VERSION = "deciles-floor-p*10-v1"  # same rule as evidence._band / SQL width_bucket(p,0,1,10)
CHECKPOINT_STEP = 50
ALPHA = 0.05  # P(success) below this => would-warn
DEFAULT_SIMS = 2000
WARNING_ENABLED = False  # owner decision: stays False until validation + independent review pass

# Sensitivity variants. Each is (name, history window as a fraction of n, Dirichlet concentration).
# "full" uses every observed match; "recent" only the latest half (drift sensitivity, floor of
# 350 predictions); "diffuse" keeps the full history but is less certain about the world
# (concentration 0.5 spreads the Bayesian-bootstrap weights more).
VARIANTS: tuple[tuple[str, float, float], ...] = (
    ("full", 1.0, 1.0),
    ("recent", 0.5, 1.0),
    ("diffuse", 1.0, 0.5),
)


def checkpoints_up_to(n: int) -> list[int]:
    """Formal evaluation points reached by a band with n predictions: 350, 400, 450, ..."""
    if n < MIN_BAND_N:
        return []
    return list(range(MIN_BAND_N, n + 1, CHECKPOINT_STEP))


@dataclass(frozen=True)
class Projection:
    n: int
    status: str  # insufficient | ok | would_warn | unstable
    p_success: float | None  # headline: the "full" variant
    p_by_variant: dict[str, float] = field(default_factory=dict)
    observed_gap: float | None = None  # observed hit rate - mean stated probability so far
    gap_se_cluster: float | None = None  # match-clustered standard error of that gap
    n_matches: int = 0
    assumptions: tuple[str, ...] = ()
    method_version: str = METHOD_VERSION
    warning_active: bool = False  # always False while WARNING_ENABLED is False


def _prepare(probs, hits, match_ids):
    p = np.asarray(probs, dtype=float)
    y = np.asarray(hits, dtype=float)
    m = np.asarray(match_ids)
    if not (p.ndim == y.ndim == m.ndim == 1 and len(p) == len(y) == len(m)):
        raise ValueError("probs, hits and match_ids must be 1-D arrays of equal length")
    if len(p) and (p.min() < 0.0 or p.max() > 1.0):
        raise ValueError("probabilities must be within [0, 1]")
    if len(y) and not np.isin(y, (0.0, 1.0)).all():
        raise ValueError("hits must be 0/1")
    return p, y, m


def _match_table(resid: np.ndarray, match_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-match (sum of residuals y - p, prediction count), in order of first appearance."""
    _, first_idx, inv = np.unique(match_ids, return_index=True, return_inverse=True)
    order = np.argsort(first_idx)  # unique() sorts ids; restore first-appearance order
    rank = np.empty(len(order), dtype=int)
    rank[order] = np.arange(len(order))
    g = rank[inv]
    k = len(order)
    s = np.bincount(g, weights=resid, minlength=k)
    c = np.bincount(g, minlength=k).astype(float)
    return s, c


def _simulate_p_success(
    s: np.ndarray,
    c: np.ndarray,
    obs_sum: float,
    n_obs: int,
    conc: float,
    n_target: int,
    tol: float,
    sims: int,
    rng: np.random.Generator,
) -> float:
    """Share of simulated futures whose final |gap| over n_target predictions is <= tol."""
    m_rem = n_target - n_obs
    if m_rem <= 0:
        return float(abs(obs_sum / n_target) <= tol + 1e-12)
    k_matches = len(s)
    g = rng.gamma(conc, size=(sims, k_matches))
    cdf = np.cumsum(g, axis=1)
    cdf /= cdf[:, -1:]
    mean_size = float(c.mean())
    k_draw = int(np.ceil(1.5 * m_rem / mean_size)) + 10
    u = rng.random((sims, k_draw))
    offs = np.arange(sims)[:, None]
    idx = np.searchsorted((cdf + offs).ravel(), (u + offs).ravel()).reshape(sims, k_draw)
    idx -= offs * k_matches
    np.clip(idx, 0, k_matches - 1, out=idx)
    sizes = c[idx]
    cs = np.cumsum(sizes, axis=1)
    full = cs <= m_rem
    fut = (s[idx] * full).sum(axis=1)
    n_full = full.sum(axis=1)
    rows = np.arange(sims)
    covered = np.where(n_full > 0, cs[rows, np.maximum(n_full - 1, 0)], 0.0)
    left = m_rem - covered
    has_next = n_full < k_draw
    nxt = np.minimum(n_full, k_draw - 1)
    # Pro-rata share of the next (partial) match; if every draw was consumed, extend with the
    # world's own mean residual per prediction.
    frac = np.where(has_next, left / sizes[rows, nxt], 0.0)
    fut = fut + np.where(has_next, frac * s[idx[rows, nxt]], 0.0)
    wmean = (g * s).sum(axis=1) / (g * c).sum(axis=1)
    fut = fut + np.where(has_next, 0.0, left * wmean)
    final_gap = (obs_sum + fut) / n_target
    return float(np.mean(np.abs(final_gap) <= tol + 1e-12))


def _cluster_se(s: np.ndarray, c: np.ndarray, n: int) -> float:
    """Standard error of the pooled gap with matches as the independent units."""
    gap = s.sum() / n
    k = len(s)
    if k < 2:
        return float("nan")
    d = s - gap * c
    return float(np.sqrt(k / (k - 1) * (d * d).sum()) / n)


def project(
    probs,
    hits,
    match_ids,
    *,
    unit_ids=None,
    n_target: int = MATURE_N,
    tol: float = TOL_FINAL,
    sims: int = DEFAULT_SIMS,
    seed: int = 20261029,
    variants: tuple[tuple[str, float, float], ...] = VARIANTS,
) -> Projection:
    """Projection for one band using all n supplied predictions (time-ordered).

    unit_ids: optional coarser resampling unit than the match (for example a matchweek id).
    When given, whole units are resampled, so dependence ACROSS the matches of a unit (a shared
    matchweek effect) is respected as well as dependence within a match. Cost: fewer, larger
    units, so the projection is less certain at small n. Default: resample by match."""
    p, y, m = _prepare(probs, hits, match_ids)
    if unit_ids is not None:
        u = np.asarray(unit_ids)
        if u.shape != m.shape:
            raise ValueError("unit_ids must have the same length as match_ids")
        m = u
    n = len(p)
    assumptions = (
        "Future matches resemble observed matches (same stated-probability mix and match sizes).",
        "Matches, not predictions, are the independent units; props on one match stay together.",
        "The band's true calibration gap is uncertain and is carried through a Bayesian bootstrap.",
        "Observed results are kept; only the remaining predictions to the target are simulated.",
    )
    if n < MIN_BAND_N:
        return Projection(n=n, status="insufficient", p_success=None, assumptions=assumptions)
    resid = y - p
    s_all, c_all = _match_table(resid, m)
    pv: dict[str, float] = {}
    for j, (name, window, conc) in enumerate(variants):
        if window < 1.0:
            keep = max(MIN_BAND_N, int(round(n * window)))
            s_w, c_w = _match_table(resid[-keep:], m[-keep:])
        else:
            s_w, c_w = s_all, c_all
        # The observed total always comes from ALL n predictions; the window only shapes the
        # world that the remaining predictions are drawn from.
        rng = np.random.default_rng([seed, n, j])
        pv[name] = _simulate_p_success(
            s_w, c_w, float(s_all.sum()), n, conc, n_target, tol, sims, rng
        )
    head = pv[variants[0][0]]
    below = [v < ALPHA for v in pv.values()]
    if all(below):
        status = "would_warn"
    elif any(below):
        status = "unstable"
    else:
        status = "ok"
    return Projection(
        n=n,
        status=status,
        p_success=head,
        p_by_variant=pv,
        observed_gap=float(resid.mean()),
        gap_se_cluster=_cluster_se(s_all, c_all, n),
        n_matches=len(s_all),
        assumptions=assumptions,
        warning_active=WARNING_ENABLED and status == "would_warn",
    )


def formal_status(probs, hits, match_ids, *, unit_ids=None, **kw) -> Projection:
    """Status at the latest checkpoint reached (350, 400, ...). Predictions after that
    checkpoint do not change the formal status until the next checkpoint is reached."""
    p, y, m = _prepare(probs, hits, match_ids)
    cps = checkpoints_up_to(len(p))
    c = cps[-1] if cps else len(p)
    u = None if unit_ids is None else np.asarray(unit_ids)[:c]
    return project(p[:c], y[:c], m[:c], unit_ids=u, **kw)


@dataclass(frozen=True)
class SequenceResult:
    checkpoints: list[int]
    statuses: list[str]
    p_success: list[float]
    first_warn_n: int | None  # first checkpoint with status would_warn
    first_unstable_n: int | None
    ever_warned: bool
    currently_warned: bool
    warn_checkpoints: int  # how many checkpoints were would_warn (repeat behaviour)


def sequence_status(probs, hits, match_ids, *, unit_ids=None, **kw) -> SequenceResult:
    """Replay every checkpoint in order, so repeated monitoring is explicit."""
    p, y, m = _prepare(probs, hits, match_ids)
    cps = checkpoints_up_to(len(p))
    statuses, ps = [], []
    for c in cps:
        u = None if unit_ids is None else np.asarray(unit_ids)[:c]
        r = project(p[:c], y[:c], m[:c], unit_ids=u, **kw)
        statuses.append(r.status)
        ps.append(r.p_success)
    warn = [c for c, s in zip(cps, statuses) if s == "would_warn"]
    unst = [c for c, s in zip(cps, statuses) if s == "unstable"]
    return SequenceResult(
        checkpoints=cps,
        statuses=statuses,
        p_success=ps,
        first_warn_n=warn[0] if warn else None,
        first_unstable_n=unst[0] if unst else None,
        ever_warned=bool(warn),
        currently_warned=bool(statuses) and statuses[-1] == "would_warn",
        warn_checkpoints=len(warn),
    )


def persistent_warn_n(result: SequenceResult, k: int) -> int | None:
    """First checkpoint at which would_warn has held for k consecutive checkpoints (k >= 1).

    A candidate repeated-monitoring rule: one noisy checkpoint no longer raises the review
    trigger. It delays every true detection by (k - 1) * CHECKPOINT_STEP predictions."""
    if k < 1:
        raise ValueError("k must be >= 1")
    run = 0
    for c, s in zip(result.checkpoints, result.statuses):
        run = run + 1 if s == "would_warn" else 0
        if run >= k:
            return c
    return None


def band_ids(probs) -> np.ndarray:
    """Fixed decile band (1-10) per prediction, same rule as evidence.py and v_calibration."""
    return _band(np.asarray(probs, dtype=float))
