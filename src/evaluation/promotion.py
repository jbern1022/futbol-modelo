"""
Model governance core (Todoist 6hqqP99w59C6F7vf, ADR-021): pure decision logic.

One approved champion serves each league/market cohort; shadow challengers are
scored in isolation and never published. A challenger needs >=1,250 graded live
predictions, independent validation and explicit approvals before the owner may
promote it. Nothing here promotes, relegates or writes anything: the functions
return evidence and blockers, and `auto_promote` is always False.

Head-to-head compares the champion and a challenger on the SAME predictions
(matched on fixture / market / line / side / subject, optionally as of a cutoff)
using Brier, log loss, reliability bins and a cluster bootstrap over fixtures. It
reports which way the evidence points; it does not pick a winner and it does not
require another 1,250 predictions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

CHALLENGER_MIN_GRADED = 1250
CLIP = (1e-6, 1 - 1e-6)


def _loss_brier(p, y):
    return (p - y) ** 2


def _loss_log(p, y):
    p = np.clip(p, *CLIP)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _reliability(p, y):
    bands = np.minimum((p * 10).astype(int), 9) + 1
    return [{"band": int(b), "n": int((bands == b).sum()),
             "avg_p": float(p[bands == b].mean()), "rate": float(y[bands == b].mean())}
            for b in sorted(set(bands.tolist()))]


def _paired(loss, p_a, p_b, y, cluster_idx, n_boot, seed):
    d = loss(p_b, y) - loss(p_a, y)  # challenger minus champion; negative = challenger better
    n_clusters = int(cluster_idx.max()) + 1
    sums = np.bincount(cluster_idx, weights=d, minlength=n_clusters)
    cnts = np.bincount(cluster_idx, minlength=n_clusters).astype(float)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=n_boot)
    boots = (w @ sums) / (w @ cnts)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"champion": float(loss(p_a, y).mean()), "challenger": float(loss(p_b, y).mean()),
            "diff": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi)}


def head_to_head(champion_rows: list[dict], challenger_rows: list[dict],
                 cutoff: datetime | None = None, n_boot: int = 1000, seed: int = 0) -> dict:
    """Rows: {key, cluster, p, hit, locked_at}. `key` identifies the same prediction."""
    def keep(rows):
        return {r["key"]: r for r in rows if cutoff is None or r["locked_at"] <= cutoff}
    a, b = keep(champion_rows), keep(challenger_rows)
    shared = sorted(set(a) & set(b), key=repr)
    out = {"n_matched": len(shared), "n_champion_only": len(set(a) - set(b)),
           "n_challenger_only": len(set(b) - set(a)), "cutoff": cutoff,
           "auto_promote": False, "winner_selected": False}
    if not shared:
        return {**out, "verdict": "INCONCLUSIVE"}
    p_a = np.array([a[k]["p"] for k in shared])
    p_b = np.array([b[k]["p"] for k in shared])
    y = np.array([a[k]["hit"] for k in shared])
    if not np.array_equal(y, np.array([b[k]["hit"] for k in shared])):
        raise ValueError("matched predictions disagree on the outcome")
    _, cidx = np.unique([a[k]["cluster"] for k in shared], return_inverse=True)
    brier = _paired(_loss_brier, p_a, p_b, y, cidx, n_boot, seed)
    logl = _paired(_loss_log, p_a, p_b, y, cidx, n_boot, seed)
    if brier["ci_high"] < 0 and logl["ci_high"] < 0:
        verdict = "CHALLENGER_AHEAD"
    elif brier["ci_low"] > 0 and logl["ci_low"] > 0:
        verdict = "CHAMPION_AHEAD"
    else:
        verdict = "INCONCLUSIVE"
    return {**out, "brier": brier, "log_loss": logl, "verdict": verdict,
            "reliability": {"champion": _reliability(p_a, y), "challenger": _reliability(p_b, y)}}


@dataclass(frozen=True)
class PromotionCase:
    challenger_graded_n: int
    independent_validation: bool
    champion_failed: bool
    root_cause_approved: bool | None
    promotion_approved_by: str | None
    rollback_version: str | None
    head_to_head_verdict: str | None


@dataclass
class Blockers:
    blockers: list[str] = field(default_factory=list)
    auto_promote: bool = False

    @property
    def eligible_for_owner_decision(self) -> bool:
        return not self.blockers


def promotion_blockers(case: PromotionCase) -> Blockers:
    out = Blockers()
    if case.challenger_graded_n < CHALLENGER_MIN_GRADED:
        out.blockers.append(f"challenger has {case.challenger_graded_n} graded live predictions; "
                            f"needs {CHALLENGER_MIN_GRADED} (1250)")
    if not case.independent_validation:
        out.blockers.append("no independent validation recorded")
    if case.champion_failed and case.root_cause_approved is not True:
        out.blockers.append("champion failed: root cause and corrective evidence not approved")
    if not case.promotion_approved_by:
        out.blockers.append("no explicit promotion approval recorded")
    if not case.rollback_version:
        out.blockers.append("no rollback version recorded")
    if case.head_to_head_verdict == "INCONCLUSIVE":
        out.blockers.append("head-to-head is inconclusive: keep the champion and collect more evidence")
    elif case.head_to_head_verdict == "CHAMPION_AHEAD":
        out.blockers.append("head-to-head favours the champion")
    elif case.head_to_head_verdict is None:
        out.blockers.append("no head-to-head on matched predictions")
    return out


def route_cohort(champion: dict | None, shadows: list[str]) -> dict:
    """Which version serves a league/market cohort. Shadows never publish and never
    stand in for a missing champion."""
    out = {"shadow_versions": list(shadows), "shadows_publish": False}
    if champion and champion.get("approved") and champion.get("reliable"):
        return {**out, "action": "SERVE_CHAMPION", "serve": champion["version"]}
    return {**out, "action": "SUSPEND_PRIMARY", "serve": None}
