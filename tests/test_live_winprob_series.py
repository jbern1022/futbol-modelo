"""
Series behind the in-play chart (GET /v1/fixtures/{match_id}/live-winprob).
Checked against a real stored series: MLS match 4606, 2-1 home win, 111
ticks, ~19 of them parked at minute 45 (halftime) and several at 90
(stoppage, where status.elapsed caps). Read-only.
"""
import os

import psycopg2
import pytest

from api.live_winprob import live_events, live_series

DSN = os.environ.get("FUTBOL_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")
MATCH_ID = 4606


@pytest.fixture
def cur():
    c = psycopg2.connect(DSN)
    yield c.cursor()
    c.rollback()
    c.close()


def test_unknown_match_has_no_series(cur):
    assert live_series(cur, -1) == []


def test_parked_ticks_collapse_to_one_point_per_minute_and_score(cur):
    series = live_series(cur, MATCH_ID)
    if not series:
        pytest.skip("match 4606's series is not in this database")
    keys = [(p["minute"], p["home_score"], p["away_score"]) for p in series]
    assert len(keys) == len(set(keys))
    assert len(series) < 111
    assert [p["minute"] for p in series] == sorted(p["minute"] for p in series)


def test_series_ends_on_the_real_final_score(cur):
    series = live_series(cur, MATCH_ID)
    if not series:
        pytest.skip("match 4606's series is not in this database")
    last = series[-1]
    assert (last["home_score"], last["away_score"]) == (2, 1)
    assert last["home"] > 0.95
    assert abs(last["home"] + last["draw"] + last["away"] - 1) < 1e-3


def test_events_are_goals_and_red_cards_with_a_side(cur):
    cur.execute("SELECT match_id FROM futbol.match_events WHERE type = 'Goal' LIMIT 1")
    row = cur.fetchone()
    if row is None:
        pytest.skip("no match_events in this database")
    events = live_events(cur, row[0])
    assert events
    for e in events:
        assert e["side"] in ("home", "away")
        assert e["type"] == "Goal" or "red" in e["detail"].lower()
