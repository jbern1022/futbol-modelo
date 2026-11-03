"""Point-in-time rest, congestion and travel features."""
from datetime import datetime, timedelta, timezone

import pytest

from features import workload as w

UTC = timezone.utc


def dt(d, h=15):
    return datetime(2026, 10, d, h, 0, tzinfo=UTC)


def test_haversine_known_distances():
    # London -> Paris ~ 344 km; Seattle -> Miami ~ 4,380 km; same point = 0
    assert w.haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(344, abs=3)
    assert w.haversine_km(47.6062, -122.3321, 25.7617, -80.1918) == pytest.approx(4380, abs=40)
    assert w.haversine_km(10, 10, 10, 10) == 0.0
    # symmetric
    assert w.haversine_km(1, 2, 3, 4) == pytest.approx(w.haversine_km(3, 4, 1, 2))


def test_rest_and_congestion_counts():
    fx = [w.Fixture(dt(1)), w.Fixture(dt(5)), w.Fixture(dt(8)), w.Fixture(dt(12))]
    f = w.workload(fx, dt(14))
    assert f["rest_days"] == pytest.approx(2.0)
    assert f["n_7d"] == 2  # Oct 8 and Oct 12 (Oct 7 15:00 cut-off)
    assert f["n_14d"] == 4
    assert f["n_prior"] == 4


def test_no_leakage_future_and_in_progress_fixtures_ignored():
    cutoff = dt(10)
    fx = [
        w.Fixture(dt(8)),
        w.Fixture(dt(10, 14)),   # kicked off one hour before cutoff: still in progress
        w.Fixture(dt(10, 15)),   # kicks off AT the cutoff
        w.Fixture(dt(11)),       # in the future
    ]
    f = w.workload(fx, cutoff)
    assert f["n_prior"] == 1
    assert f["rest_days"] == pytest.approx(2.0)
    # a fixture that finished exactly at the cutoff counts
    assert w.workload([w.Fixture(dt(10, 13))], cutoff)["n_prior"] == 1


def test_missing_history_is_none_not_large():
    f = w.workload([], dt(10))
    assert f["rest_days"] is None and f["n_7d"] == 0 and f["minutes_7d"] is None
    assert f["minutes_coverage_7d"] is None


def test_minutes_only_when_fully_covered():
    fx = [w.Fixture(dt(8), minutes=990), w.Fixture(dt(9), minutes=None), w.Fixture(dt(1), minutes=900)]
    f = w.workload(fx, dt(10))
    assert f["n_7d"] == 2
    assert f["minutes_7d"] is None            # one of two unknown -> not summed
    assert f["minutes_coverage_7d"] == 0.5
    full = w.workload([w.Fixture(dt(8), minutes=990), w.Fixture(dt(9), minutes=980)], dt(10))
    assert full["minutes_7d"] == 1970 and full["minutes_coverage_7d"] == 1.0


def test_travel_estimates_and_direction():
    seattle = w.Fixture(dt(1), venue_lat=47.6062, venue_lon=-122.3321)
    miami = w.Fixture(dt(5), venue_lat=25.7617, venue_lon=-80.1918)
    east = w.travel(seattle, miami)
    assert east["estimated"] is True
    assert east["distance_km"] == pytest.approx(4380, abs=40)
    assert east["tz_shift_hours"] == pytest.approx(2.8, abs=0.1)     # eastward is positive
    assert east["days_between"] == pytest.approx(4.0)
    west = w.travel(miami, w.Fixture(dt(9), venue_lat=47.6062, venue_lon=-122.3321))
    assert west["tz_shift_hours"] == pytest.approx(-2.8, abs=0.1)


def test_travel_unknown_coordinates_are_none():
    t = w.travel(w.Fixture(dt(1)), w.Fixture(dt(5), venue_lat=1.0, venue_lon=2.0))
    assert t["distance_km"] is None and t["tz_shift_hours"] is None and t["days_between"] == pytest.approx(4.0)
    assert w.travel(None, w.Fixture(dt(5)))["days_between"] is None


def test_features_for_match_uses_cutoff_and_blocks_post_kickoff_cutoff():
    prev = w.Fixture(dt(5), venue_lat=40.0, venue_lon=-74.0)
    other = w.Fixture(dt(9, 12), venue_lat=41.0, venue_lon=-87.0)  # finished before a late cutoff only
    nxt = w.Fixture(dt(10), venue_lat=34.0, venue_lon=-118.0)
    early = w.features_for_match([prev, other], nxt, cutoff=dt(8))
    assert early["n_prior"] == 1 and early["travel_days_between"] == pytest.approx(5.0)
    late = w.features_for_match([prev, other], nxt)
    assert late["n_prior"] == 2 and late["rest_days"] == pytest.approx(1.125)
    with pytest.raises(ValueError):
        w.features_for_match([prev], nxt, cutoff=nxt.kickoff_utc + timedelta(minutes=1))


def test_naive_datetimes_rejected():
    with pytest.raises(ValueError):
        w.workload([w.Fixture(datetime(2026, 10, 1))], dt(5))
    with pytest.raises(ValueError):
        w.workload([], datetime(2026, 10, 5))
