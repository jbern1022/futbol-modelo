"""Projected-failure estimator (development method, warning disabled). Todoist 6hm2JMm4XrQJpJcf."""
import numpy as np
import pytest

from evaluation import projected_failure as pf


def _band_data(n_matches, size=5, gap=0.0, seed=0, p_lo=0.60, p_hi=0.70):
    rng = np.random.default_rng(seed)
    p = np.repeat(rng.uniform(p_lo, p_hi, n_matches), size)
    mid = np.repeat(np.arange(n_matches), size)
    y = (rng.random(len(p)) < np.clip(p + gap, 0, 1)).astype(int)
    return p, y, mid


def test_warning_is_disabled_by_default():
    assert pf.WARNING_ENABLED is False
    p, y, mid = _band_data(100, gap=-0.10)
    r = pf.project(p, y, mid, sims=500)
    assert r.status == "would_warn"
    assert r.warning_active is False


def test_insufficient_below_350():
    p, y, mid = _band_data(60)  # 300 predictions
    r = pf.project(p, y, mid, sims=200)
    assert r.status == "insufficient" and r.p_success is None


def test_checkpoints():
    assert pf.checkpoints_up_to(349) == []
    assert pf.checkpoints_up_to(350) == [350]
    assert pf.checkpoints_up_to(449) == [350, 400]
    assert pf.checkpoints_up_to(450) == [350, 400, 450]


def test_formal_status_frozen_between_checkpoints():
    p, y, mid = _band_data(100)  # 500 predictions
    a = pf.formal_status(p[:449], y[:449], mid[:449], sims=300)
    b = pf.formal_status(p[:400], y[:400], mid[:400], sims=300)
    assert a.n == b.n == 400 and a.p_by_variant == b.p_by_variant


def test_deterministic_for_same_seed():
    p, y, mid = _band_data(80)
    a = pf.project(p, y, mid, sims=400, seed=7)
    b = pf.project(p, y, mid, sims=400, seed=7)
    assert a.p_by_variant == b.p_by_variant


def test_calibrated_band_is_not_flagged_and_off_band_is():
    p, y, mid = _band_data(100, gap=0.0, seed=3)
    assert pf.project(p, y, mid, sims=600).status in ("ok", "unstable")
    p, y, mid = _band_data(100, gap=-0.10, seed=3)
    assert pf.project(p, y, mid, sims=600).status == "would_warn"


def test_already_decided_when_target_reached():
    p, y, mid = _band_data(250, gap=0.0, seed=5)  # 1,250 predictions
    r = pf.project(p, y, mid, sims=100)
    assert r.p_success in (0.0, 1.0)


def test_matches_are_the_independent_unit():
    # Perfectly correlated props on a match: the cluster SE must be far larger than the
    # naive independent-prediction SE, and the projection must be less certain for it.
    rng = np.random.default_rng(11)
    k = 80
    p = np.full(k * 5, 0.65)
    mid = np.repeat(np.arange(k), 5)
    ym = (rng.random(k) < 0.65).astype(int)
    y_dep = np.repeat(ym, 5)  # all 5 props hit or miss together
    y_ind = (rng.random(k * 5) < 0.65).astype(int)
    dep = pf.project(p, y_dep, mid, sims=600)
    ind = pf.project(p, y_ind, mid, sims=600)
    assert dep.gap_se_cluster > 1.8 * ind.gap_se_cluster


def test_unstable_when_variants_straddle_the_line():
    # Strong recent deterioration after a long calibrated run: full history looks fine,
    # recent window disagrees.
    p1, y1, m1 = _band_data(120, gap=0.0, seed=1)
    p2, y2, m2 = _band_data(30, gap=-0.25, seed=2)
    p = np.concatenate([p1, p2])
    y = np.concatenate([y1, y2])
    m = np.concatenate([m1, m2 + 1000])
    r = pf.project(p, y, m, sims=800)
    flags = [v < pf.ALPHA for v in r.p_by_variant.values()]
    assert any(flags) and not all(flags)
    assert r.status == "unstable"


def test_sequence_status_replays_checkpoints():
    p, y, mid = _band_data(120, gap=-0.10, seed=4)  # 600 predictions
    s = pf.sequence_status(p, y, mid, sims=300)
    assert s.checkpoints == list(range(350, 601, 50))
    assert s.ever_warned and s.first_warn_n is not None
    assert s.warn_checkpoints >= 1


def test_input_validation():
    with pytest.raises(ValueError):
        pf.project([0.5, 1.2], [1, 0], [1, 2])
    with pytest.raises(ValueError):
        pf.project([0.5, 0.5], [1, 2], [1, 2])
    with pytest.raises(ValueError):
        pf.project([0.5], [1, 0], [1, 2])


def test_band_rule_matches_evidence_module():
    from evaluation.evidence import _band
    probs = np.array([0.0, 0.0999, 0.1, 0.6, 0.65, 0.7, 0.999, 1.0])
    assert (pf.band_ids(probs) == _band(probs)).all()
    assert pf.band_ids(probs)[-1] == 10


def test_unit_ids_default_equals_match_ids():
    p, y, mid = _band_data(80, seed=9)
    a = pf.project(p, y, mid, sims=300, seed=1)
    b = pf.project(p, y, mid, unit_ids=mid, sims=300, seed=1)
    assert a.p_by_variant == b.p_by_variant


def test_week_units_widen_uncertainty_when_weeks_share_an_effect():
    # 10 matches (50 predictions) per week share one additive shift; resampling whole weeks must
    # report a larger clustered SE than resampling matches.
    rng = np.random.default_rng(21)
    weeks, per = 12, 10
    k = weeks * per
    p = np.repeat(rng.uniform(0.6, 0.7, k), 5)
    mid = np.repeat(np.arange(k), 5)
    wk = np.repeat(np.arange(weeks), per * 5)
    shift = np.repeat(rng.normal(0, 0.06, weeks), per * 5)
    y = (rng.random(len(p)) < np.clip(p + shift, 0, 1)).astype(int)
    by_match = pf.project(p, y, mid, sims=300)
    by_week = pf.project(p, y, mid, unit_ids=wk, sims=300)
    assert by_week.gap_se_cluster > 1.3 * by_match.gap_se_cluster
    assert by_week.n_matches == weeks


def test_unit_ids_length_checked():
    p, y, mid = _band_data(80)
    with pytest.raises(ValueError):
        pf.project(p, y, mid, unit_ids=mid[:-1], sims=100)


def test_persistent_warn_n():
    r = pf.SequenceResult(
        checkpoints=[350, 400, 450, 500, 550],
        statuses=["ok", "would_warn", "ok", "would_warn", "would_warn"],
        p_success=[0.5] * 5, first_warn_n=400, first_unstable_n=None,
        ever_warned=True, currently_warned=True, warn_checkpoints=3,
    )
    assert pf.persistent_warn_n(r, 1) == 400
    assert pf.persistent_warn_n(r, 2) == 550
    assert pf.persistent_warn_n(r, 3) is None
    with pytest.raises(ValueError):
        pf.persistent_warn_n(r, 0)
