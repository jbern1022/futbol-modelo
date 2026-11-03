"""
Point-in-time workload and travel features for soccer forecasts (Todoist 6hf57M7W6CgXjH77,
6hf54j2hMP87xjR7, 6hf57M8HM6RW6X4f, 6hf57MCf77fRr9Xf). Pure functions: no database, no I/O.

Rules every function here follows:
 * POINT IN TIME. A feature for a forecast is computed from fixtures that had finished by the
   forecast cutoff (kickoff + MATCH_DURATION <= cutoff). A fixture that kicks off after the
   cutoff, or that was still in progress, is never used, even if the caller passes it in.
 * MISSINGNESS IS EXPLICIT. If a team has no earlier fixture in the supplied data, rest is None,
   not a large number; minutes are None unless EVERY counted fixture has a minutes value, and a
   coverage fraction is returned beside them.
 * DISTANCE AND TIME ZONE ARE ESTIMATES. Great-circle distance between two venue coordinates and a
   solar-time offset (longitude / 15) are rough proxies for travel; they are NOT flight itineraries
   or civil time zones, and every result says so in its `estimated` flag.
 * No home advantage is added or removed here; these are inputs for experiments only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

EARTH_RADIUS_KM = 6371.0088
MATCH_DURATION = timedelta(hours=2)  # kickoff to final whistle incl. stoppage, for "already finished"


@dataclass(frozen=True)
class Fixture:
    kickoff_utc: datetime  # timezone-aware, UTC
    competition: str = ""
    venue_lat: float | None = None
    venue_lon: float | None = None
    minutes: float | None = None  # minutes this team's players/starters logged, if known
    neutral: bool = False


def _check_aware(*dts: datetime) -> None:
    for d in dts:
        if d.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware (UTC)")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def solar_offset_hours(lon: float) -> float:
    """Solar-time offset from UTC in hours (longitude / 15). An ESTIMATE of local time shift:
    civil time zones and daylight saving can differ by an hour or more."""
    return lon / 15.0


def played_before(fixtures: list[Fixture], cutoff: datetime) -> list[Fixture]:
    """Fixtures finished by the cutoff, oldest first. Later or in-progress fixtures are dropped."""
    _check_aware(cutoff)
    out = []
    for f in fixtures:
        _check_aware(f.kickoff_utc)
        if f.kickoff_utc + MATCH_DURATION <= cutoff:
            out.append(f)
    return sorted(out, key=lambda f: f.kickoff_utc)


def workload(fixtures: list[Fixture], cutoff: datetime, windows: tuple[int, ...] = (7, 14)) -> dict:
    """Rest, congestion and minutes for one team as of `cutoff`.

    Returns {'rest_days', 'n_<w>d' per window, 'minutes_<w>d' per window,
    'minutes_coverage_<w>d' per window, 'n_prior'}. rest_days is None with no earlier fixture."""
    prior = played_before(fixtures, cutoff)
    out: dict = {"n_prior": len(prior)}
    if prior:
        out["rest_days"] = (cutoff - prior[-1].kickoff_utc).total_seconds() / 86400
    else:
        out["rest_days"] = None
    for w in windows:
        inw = [f for f in prior if f.kickoff_utc >= cutoff - timedelta(days=w)]
        out[f"n_{w}d"] = len(inw)
        known = [f.minutes for f in inw if f.minutes is not None]
        out[f"minutes_coverage_{w}d"] = (len(known) / len(inw)) if inw else None
        out[f"minutes_{w}d"] = sum(known) if inw and len(known) == len(inw) else None
    return out


def travel(prev: Fixture | None, nxt: Fixture) -> dict:
    """Estimated travel from the previous fixture's venue to the next one's.

    Returns distance_km, tz_shift_hours (signed: positive = travelling east, so the body clock must
    advance), days_between, and `estimated` (always True). Fields are None when a coordinate is
    unknown or either fixture is at a neutral venue we cannot place."""
    out: dict[str, float | bool | None] = {
        "distance_km": None, "tz_shift_hours": None, "days_between": None, "estimated": True,
    }
    if prev is None:
        return out
    _check_aware(prev.kickoff_utc, nxt.kickoff_utc)
    out["days_between"] = (nxt.kickoff_utc - prev.kickoff_utc).total_seconds() / 86400
    lat0, lon0, lat1, lon1 = prev.venue_lat, prev.venue_lon, nxt.venue_lat, nxt.venue_lon
    if lat0 is None or lon0 is None or lat1 is None or lon1 is None:
        return out
    out["distance_km"] = haversine_km(lat0, lon0, lat1, lon1)
    out["tz_shift_hours"] = solar_offset_hours(lon1) - solar_offset_hours(lon0)
    return out


def features_for_match(
    team_fixtures: list[Fixture], next_fixture: Fixture, cutoff: datetime | None = None
) -> dict:
    """All workload and travel features for one team before `next_fixture`.

    The cutoff defaults to the next fixture's kickoff and may be EARLIER (a morning forecast
    cutoff) but never later: a cutoff after kickoff would let the match itself leak in."""
    _check_aware(next_fixture.kickoff_utc)
    cutoff = cutoff or next_fixture.kickoff_utc
    _check_aware(cutoff)
    if cutoff > next_fixture.kickoff_utc:
        raise ValueError("cutoff must not be later than the next fixture's kickoff")
    prior = [f for f in played_before(team_fixtures, cutoff) if f.kickoff_utc < next_fixture.kickoff_utc]
    feats = workload(prior, cutoff)
    feats.update({f"travel_{k}": v for k, v in travel(prior[-1] if prior else None, next_fixture).items()})
    return feats
