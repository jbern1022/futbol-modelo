"""
Model governance (Todoist 6hqqP99w59C6F7vf): one champion per cohort, shadow
challengers that never influence production, >=1,250 graded live predictions per
challenger, matched head-to-head, explicit approvals, versioned rollback, and
NEVER an automatic promotion.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from evaluation.promotion import (
    CHALLENGER_MIN_GRADED, PromotionCase, head_to_head, promotion_blockers, route_cohort,
)

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _rows(ps, ys, offset=0, locked=None):
    """prediction rows keyed by (match_id, market, line, side, subject)."""
    return [{"key": (offset + i, "CORNERS", 4.5, "over", None), "cluster": offset + i,
             "p": float(p), "hit": int(y), "locked_at": locked or T0}
            for i, (p, y) in enumerate(zip(ps, ys))]


def _world(n=2000, seed=0, chall_noise=0.0):
    rng = np.random.default_rng(seed)
    true = rng.uniform(0.2, 0.8, n)
    y = (rng.uniform(size=n) < true).astype(int)
    champ = np.clip(true + rng.normal(0, 0.12, n), 0.02, 0.98)
    sd = 0.12 + chall_noise if chall_noise else 0.03
    chall = np.clip(true + rng.normal(0, sd, n), 0.02, 0.98)
    return y, champ, chall


def test_head_to_head_matches_only_shared_keys_and_reports_unmatched():
    y, champ, chall = _world(400)
    a, b = _rows(champ, y), _rows(chall[:300], y[:300])
    r = head_to_head(a, b, n_boot=200)
    assert r["n_matched"] == 300 and r["n_champion_only"] == 100 and r["n_challenger_only"] == 0


def test_cutoff_excludes_predictions_locked_after_it():
    y, champ, chall = _world(300)
    late = T0 + timedelta(days=5)
    a = _rows(champ, y)
    b = _rows(chall, y)
    for row in b[:100]:
        row["locked_at"] = late
    r = head_to_head(a, b, cutoff=T0 + timedelta(days=1), n_boot=200)
    assert r["n_matched"] == 200


def test_clearly_better_challenger_is_ahead_but_nothing_is_promoted():
    y, champ, chall = _world(3000)
    r = head_to_head(_rows(champ, y), _rows(chall, y), n_boot=400)
    assert r["verdict"] == "CHALLENGER_AHEAD"
    assert r["brier"]["diff"] < 0 and r["brier"]["ci_high"] < 0
    assert r["auto_promote"] is False and r["winner_selected"] is False


def test_clearly_worse_challenger_is_champion_ahead():
    y, champ, chall = _world(3000, chall_noise=0.25)
    r = head_to_head(_rows(champ, y), _rows(chall, y), n_boot=400)
    assert r["verdict"] == "CHAMPION_AHEAD"


def test_identical_models_are_inconclusive():
    y, champ, _ = _world(1500)
    r = head_to_head(_rows(champ, y), _rows(champ, y), n_boot=200)
    assert r["verdict"] == "INCONCLUSIVE"


def test_head_to_head_does_not_demand_another_1250():
    y, champ, chall = _world(600)  # < 1250 matched; still evaluable, CI carries the uncertainty
    r = head_to_head(_rows(champ, y), _rows(chall, y), n_boot=200)
    assert r["n_matched"] == 600 and r["verdict"] in {"CHALLENGER_AHEAD", "CHAMPION_AHEAD", "INCONCLUSIVE"}


def test_reports_reliability_and_log_loss():
    y, champ, chall = _world(1000)
    r = head_to_head(_rows(champ, y), _rows(chall, y), n_boot=100)
    ll = r["log_loss"]
    assert {"brier", "log_loss"} <= set(r) and ll["ci_low"] <= ll["diff"] <= ll["ci_high"]
    assert len(r["reliability"]["champion"]) and len(r["reliability"]["challenger"])


def _case(**kw):
    base = dict(challenger_graded_n=1300, independent_validation=True, champion_failed=False,
                root_cause_approved=None, promotion_approved_by="joe", rollback_version="v12",
                head_to_head_verdict="CHALLENGER_AHEAD")
    base.update(kw)
    return PromotionCase(**base)


def test_complete_case_has_no_blockers_but_still_no_auto_promotion():
    b = promotion_blockers(_case())
    assert b.blockers == [] and b.eligible_for_owner_decision is True and b.auto_promote is False


@pytest.mark.parametrize("kw,needle", [
    (dict(challenger_graded_n=CHALLENGER_MIN_GRADED - 1), "1250"),
    (dict(independent_validation=False), "independent validation"),
    (dict(promotion_approved_by=None), "promotion approval"),
    (dict(rollback_version=None), "rollback"),
    (dict(head_to_head_verdict="INCONCLUSIVE"), "inconclusive"),
    (dict(head_to_head_verdict="CHAMPION_AHEAD"), "champion"),
    (dict(champion_failed=True, root_cause_approved=False), "root cause"),
    (dict(champion_failed=True, root_cause_approved=None), "root cause"),
])
def test_each_missing_requirement_blocks(kw, needle):
    b = promotion_blockers(_case(**kw))
    assert b.eligible_for_owner_decision is False
    assert any(needle in x for x in b.blockers), b.blockers


def test_failed_champion_with_approved_root_cause_can_proceed():
    b = promotion_blockers(_case(champion_failed=True, root_cause_approved=True))
    assert b.blockers == []


def test_route_serves_approved_reliable_champion_and_shadows_never_publish():
    r = route_cohort(champion={"version": "v12", "approved": True, "reliable": True},
                     shadows=["v13", "v14"])
    assert r["action"] == "SERVE_CHAMPION" and r["serve"] == "v12"
    assert r["shadow_versions"] == ["v13", "v14"] and r["shadows_publish"] is False


@pytest.mark.parametrize("champ", [None, {"version": "v12", "approved": False, "reliable": True},
                                   {"version": "v12", "approved": True, "reliable": False}])
def test_no_reliable_approved_champion_suspends_primary_and_shadows_do_not_fill_in(champ):
    r = route_cohort(champion=champ, shadows=["v13"])
    assert r["action"] == "SUSPEND_PRIMARY" and r["serve"] is None
    assert r["shadows_publish"] is False
