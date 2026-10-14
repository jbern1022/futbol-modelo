"""backfill_team_fixtures.py parsing: friendlies are dropped, home/away is
taken from the team's own API id."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from backfill_team_fixtures import rows_for_team  # noqa: E402


def _fx(fid, league, home_id, away_id):
    return {"fixture": {"id": fid, "date": "2025-01-01T15:00:00+00:00", "status": {"short": "FT"}},
            "league": {"id": 1, "name": league},
            "teams": {"home": {"id": home_id}, "away": {"id": away_id}}}


def test_friendlies_are_dropped_and_home_is_detected():
    rows = rows_for_team(7, 42, [_fx(1, "Premier League", 42, 9), _fx(2, "Friendlies Clubs", 42, 9),
                                 _fx(3, "UEFA Champions League", 9, 42)])
    assert [(r[1], r[3], r[5]) for r in rows] == [(1, "Premier League", True), (3, "UEFA Champions League", False)]
