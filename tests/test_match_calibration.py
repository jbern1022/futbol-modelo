"""
Match-market calibration: does it actually correct miscalibration, and does it
refuse to act when it has no business acting?

No database. The fixture builds a deliberately overconfident predictor — the
failure mode Poisson-derived probabilities actually have — so "the calibrator
improves things" is a real assertion.
"""
from __future__ import annotations

import numpy as np
import pytest

from models.match_calibration import (
    MIN_CALIBRATION_SAMPLES,
    MatchCalibrator,
    brier,
    log_loss,
    market_key,
)


def overconfident_records(n: int = 2000, seed: int = 0) -> list[dict]:
    """
    Stated probabilities pushed away from 0.5 relative to the truth — a model
    claiming 80% when it is right 70% of the time, and 20% when it is right 30%.
    """
    rng = np.random.default_rng(seed)
    true_p = rng.uniform(0.15, 0.85, n)
    stated = np.clip(0.5 + (true_p - 0.5) * 1.45, 0.01, 0.99)
    outcomes = rng.binomial(1, true_p)
    return [{"market": "BTTS", "side": "yes", "line": None,
             "prob": float(s), "outcome": int(o)}
            for s, o in zip(stated, outcomes)], true_p, stated, outcomes


@pytest.fixture(scope="module")
def fitted():
    records, _, _, _ = overconfident_records()
    train, test = records[:1400], records[1400:]
    return MatchCalibrator().fit(train), test


# ---------- it corrects the thing it exists to correct ----------

def test_calibration_improves_brier_on_held_out_data(fitted):
    cal, test = fitted
    raw = np.array([r["prob"] for r in test])
    out = np.array([r["outcome"] for r in test])
    adj = np.array([cal.apply("BTTS", "yes", p) for p in raw])
    assert brier(adj, out) < brier(raw, out)


def test_calibration_improves_log_loss_on_held_out_data(fitted):
    cal, test = fitted
    raw = np.array([r["prob"] for r in test])
    out = np.array([r["outcome"] for r in test])
    adj = np.array([cal.apply("BTTS", "yes", p) for p in raw])
    assert log_loss(adj, out) < log_loss(raw, out)


def test_calibration_pulls_overconfident_probabilities_toward_the_middle(fitted):
    cal, _ = fitted
    assert cal.apply("BTTS", "yes", 0.90) < 0.90
    assert cal.apply("BTTS", "yes", 0.10) > 0.10


def test_isotonic_preserves_ordering(fitted):
    """Monotone by construction: a fixture the raw model preferred must stay
    preferred. Calibration changes the level, never the ranking."""
    cal, _ = fitted
    probs = np.linspace(0.05, 0.95, 40)
    adjusted = [cal.apply("BTTS", "yes", p) for p in probs]
    assert all(a <= b + 1e-12 for a, b in zip(adjusted, adjusted[1:]))


# ---------- it declines to act without evidence ----------

def test_unknown_market_passes_through_unchanged(fitted):
    cal, _ = fitted
    assert cal.apply("TOTAL_GOALS", "over", 0.63, line=2.5) == 0.63
    assert not cal.has("TOTAL_GOALS", "over", 2.5)


def test_too_few_samples_is_skipped():
    records = [{"market": "BTTS", "side": "yes", "line": None,
                "prob": 0.6, "outcome": i % 2}
               for i in range(MIN_CALIBRATION_SAMPLES - 1)]
    cal = MatchCalibrator().fit(records)
    assert not cal.has("BTTS", "yes")
    assert "only" in str(cal.metadata["skipped"])


def test_single_outcome_class_is_skipped():
    records = [{"market": "BTTS", "side": "yes", "line": None,
                "prob": 0.6, "outcome": 1}
               for _ in range(MIN_CALIBRATION_SAMPLES + 50)]
    cal = MatchCalibrator().fit(records)
    assert not cal.has("BTTS", "yes")


def test_lines_are_calibrated_separately():
    """Over 2.5 and over 3.5 are different questions and must not share a
    calibrator."""
    rng = np.random.default_rng(1)
    records = []
    for line, true_p in ((2.5, 0.55), (3.5, 0.30)):
        for _ in range(MIN_CALIBRATION_SAMPLES + 100):
            records.append({"market": "TOTAL_GOALS", "side": "over", "line": line,
                            "prob": 0.5, "outcome": int(rng.random() < true_p)})
    cal = MatchCalibrator().fit(records)
    assert cal.has("TOTAL_GOALS", "over", 2.5)
    assert cal.has("TOTAL_GOALS", "over", 3.5)
    assert cal.apply("TOTAL_GOALS", "over", 0.5, line=2.5) != pytest.approx(
        cal.apply("TOTAL_GOALS", "over", 0.5, line=3.5))


# ---------- 1X2 stays a distribution ----------

def _one_x_two_records(n: int = 1500, seed: int = 3) -> list[dict]:
    rng = np.random.default_rng(seed)
    records = []
    for _ in range(n):
        p = rng.dirichlet([3.0, 2.0, 2.5])
        stated = np.clip(0.5 + (p - 0.5) * 1.4, 0.01, 0.99)
        drawn = rng.choice(3, p=p)
        for i, side in enumerate(("home", "draw", "away")):
            records.append({"market": "1X2", "side": side, "line": None,
                            "prob": float(stated[i]), "outcome": int(drawn == i)})
    return records


def test_calibrated_1x2_sums_to_one():
    cal = MatchCalibrator().fit(_one_x_two_records())
    for triple in [(0.55, 0.25, 0.20), (0.20, 0.30, 0.50), (0.80, 0.12, 0.08)]:
        h, d, a = cal.apply_1x2(*triple)
        assert h + d + a == pytest.approx(1.0, abs=1e-9)
        assert all(0.0 < v < 1.0 for v in (h, d, a))


def test_1x2_falls_back_to_raw_when_a_side_is_uncalibrated():
    """A partly-corrected triple, then renormalised, distorts every outcome.
    Better to leave all three raw."""
    records = [r for r in _one_x_two_records() if r["side"] != "draw"]
    cal = MatchCalibrator().fit(records)
    assert cal.has("1X2", "home") and not cal.has("1X2", "draw")
    assert cal.apply_1x2(0.55, 0.25, 0.20) == (0.55, 0.25, 0.20)


def test_1x2_preserves_the_favourite():
    cal = MatchCalibrator().fit(_one_x_two_records())
    h, d, a = cal.apply_1x2(0.60, 0.25, 0.15)
    assert h > d and h > a


# ---------- persistence ----------

def test_save_load_round_trip(fitted, tmp_path):
    cal, test = fitted
    path = cal.save(tmp_path / "cal.joblib")
    reloaded = MatchCalibrator.load(path)
    assert sorted(map(str, reloaded.calibrators)) == sorted(map(str, cal.calibrators))
    for r in test[:25]:
        assert reloaded.apply("BTTS", "yes", r["prob"]) == pytest.approx(
            cal.apply("BTTS", "yes", r["prob"]))


def test_load_rejects_a_mismatched_artifact_version(fitted, tmp_path):
    cal, _ = fitted
    path = cal.save(tmp_path / "stale.joblib")
    stale = MatchCalibrator.load(path)
    stale.metadata["artifact_version"] = 0
    stale.save(path)
    with pytest.raises(ValueError, match="artifact version"):
        MatchCalibrator.load(path)


def test_market_key_normalises_line_type():
    assert market_key("TOTAL_GOALS", "over", 2) == market_key("TOTAL_GOALS", "over", 2.0)
    assert market_key("BTTS", "yes", None) != market_key("BTTS", "yes", 0.5)
