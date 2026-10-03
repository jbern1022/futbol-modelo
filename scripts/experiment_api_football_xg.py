"""
Can API-Football's expected_goals stand in for Understat xG?

Found 2026-10-03: team_match_stats.xg is NULL for every 2026-27 match.
Understat xG was a one-off historical load (through 2025-26) and the
nightly refresh only pulls API-Football. The CORNERS/SOT props models use
xg_for_r5 / xg_against_r5, so this season's EPL/SERIE_A slates have
been going down LightGBM's missing-value branch (learned from MLS rows,
which never had xG). API-Football's /fixtures/statistics, which the
nightly refresh already calls, includes expected_goals.

Before filling the gap with it: on a random sample of 2025-26 matches
that have Understat xG, fetch API-Football's value and compare
(correlation, mean bias, scale). One /fixtures call per league plus one
/fixtures/statistics call per sampled match.

    python scripts/experiment_api_football_xg.py --league EPL --season 2025-26 --n 100
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import psycopg2

from experiment_redcard_calibration import build_fixture_lookup
from ingestion.api_football import _get, _session

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

SAMPLE_SQL = """
SELECT m.match_id, m.home_team_id, m.away_team_id, m.kickoff_utc::date,
       h.xg AS home_xg, a.xg AS away_xg
FROM futbol.matches m
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.team_match_stats h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
JOIN futbol.team_match_stats a ON a.match_id = m.match_id AND a.team_id = m.away_team_id
WHERE l.code = %s AND s.label = %s AND m.status = 'final'
  AND h.xg IS NOT NULL AND a.xg IS NOT NULL
ORDER BY md5(m.match_id::text)
LIMIT %s
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA"])
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    session = _session()
    lookup = build_fixture_lookup(cur, session, args.league, [args.season])
    conn.rollback()  # resolve_team_id may have touched team rows; this script writes nothing
    cur.execute(SAMPLE_SQL, (args.league, args.season, args.n))
    sample = cur.fetchall()
    conn.close()

    us, af = [], []
    for _, home_id, away_id, date, home_xg, away_xg in sample:
        fx = lookup.get((home_id, away_id, date))
        if fx is None:
            continue
        fixture_id, home_api, _ = fx
        for team in _get(session, "fixtures/statistics", {"fixture": fixture_id}):
            vals = {s["type"]: s["value"] for s in team["statistics"]}
            if vals.get("expected_goals") is None:
                continue
            us.append(float(home_xg if team["team"]["id"] == home_api else away_xg))
            af.append(float(vals["expected_goals"]))

    us_a, af_a = np.array(us), np.array(af)
    slope, intercept = np.polyfit(us_a, af_a, 1)
    print(f"{args.league} {args.season}: {len(us_a)} team-matches compared")
    print(f"   corr {np.corrcoef(us_a, af_a)[0, 1]:.3f}   mean Understat {us_a.mean():.3f}   "
          f"mean API-Football {af_a.mean():.3f}   mean abs diff {np.abs(us_a - af_a).mean():.3f}")
    print(f"   API-Football ~= {slope:.3f} * Understat + {intercept:+.3f}")


if __name__ == "__main__":
    main()
