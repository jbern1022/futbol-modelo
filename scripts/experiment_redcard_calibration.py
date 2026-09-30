"""
ADR-011 follow-up: calibrates the red-card remaining-time scoring
multiplier stubbed at 1.0 (no-op) in the live win-probability backend.
Todoist `6h9M3GgfQ5ch7wXQ`.

Backfills /fixtures/events for every EPL/SERIE_A final with a recorded
red card (team_match_stats.reds >= 1 -- cheap local filter, avoids
calling events for ~3900 matches that never had one) to get the real
red-card minute, then compares the down-team's and up-team's ACTUAL
remaining-time goals (from futbol.shots' real minute data) against
Dixon-Coles' unadjusted expectation for that same remaining time --
the same conditioning scripts/poll_live_winprob.py already uses, just
with no red-card factor applied. The ratio (actual/expected) IS the
empirical multiplier.

Scope, deliberately narrow for a first pass: single-red-card matches
only (skips matches with 2+ reds -- a second red changes the state
again mid-window, not modeled here), red card between minute 10-80
(a card in added time leaves no meaningful remaining-time signal to
measure), 'Goal' shots only (not 'Own Goal' -- rare enough to exclude
rather than risk misattributing which team it should count for).

    python scripts/experiment_redcard_calibration.py --league EPL
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

from generate_slate import fit_dixon_coles
from ingestion.api_football import (
    _get, _session, resolve_league_id, resolve_team_id,
)
from predictions.live_winprob import inplay_win_probs
from train_dixon_coles import rps

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Deliberately NOT using matches.external_ref here -- confirmed live
# (Todoist 6hfxhQccV87r4jcx) that it's a single column overloaded by
# both load_understat() ('understat:<id>') and api_football.py
# ('api-football:<id>'), and link_fixture_ids()'s WHERE external_ref
# IS NULL guard means a historical EPL/SERIE_A match (Understat-sourced
# first) can never also get an api-football ref through that path.
# Not a production bug (every upcoming fixture already has the right
# ref), but it does block this script's need to look up PAST fixtures.
# Worked around locally: pull each season's fixture list directly
# (one bulk call, same as link_fixture_ids's own approach) and match
# by team + date in-memory, without touching the DB column at all.
CANDIDATES_SQL = """
SELECT DISTINCT m.match_id, m.kickoff_utc::date, m.home_team_id, m.away_team_id,
       th.name, ta.name, m.home_score, m.away_score, se.label
FROM futbol.team_match_stats tms
JOIN futbol.matches m ON m.match_id = tms.match_id
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons se ON se.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = se.league_id
WHERE l.code = %s AND tms.reds >= 1 AND m.status = 'final';
"""


def build_fixture_lookup(cur, session, league: str, season_labels: list[str]) -> dict:
    """(our_home_team_id, our_away_team_id, date) -> (fixture_id,
    home_api_id, away_api_id), for every season that has a red-card
    candidate match -- one bulk call per season. Resolves API-Football's
    own team names to OUR team_ids via resolve_team_id (same
    alias-aware lookup api_football.py's other flows already trust),
    not a raw name-string match -- API-Football and Understat don't
    always spell a team's name identically."""
    league_id = resolve_league_id(session, league)
    lookup = {}
    for label in season_labels:
        season_start_year = int(label[:4])
        fixtures = _get(session, "fixtures", {"league": league_id, "season": season_start_year})
        for fx in fixtures:
            home_id = resolve_team_id(cur, fx["teams"]["home"]["id"], fx["teams"]["home"]["name"])
            away_id = resolve_team_id(cur, fx["teams"]["away"]["id"], fx["teams"]["away"]["name"])
            if not home_id or not away_id:
                continue
            date = pd.to_datetime(fx["fixture"]["date"]).date()
            lookup[(home_id, away_id, date)] = (
                fx["fixture"]["id"], fx["teams"]["home"]["id"], fx["teams"]["away"]["id"])
    return lookup


def fetch_red_cards(session, fixture_id: int) -> list[tuple[int, int]]:
    """Returns [(minute, team_id_api)] for every real Red Card event
    (including a second-yellow red) on this fixture."""
    events = _get(session, "fixtures/events", {"fixture": fixture_id})
    out = []
    for e in events:
        if e.get("type") == "Card" and "red" in (e.get("detail") or "").lower():
            minute = e["time"]["elapsed"]
            out.append((minute, e["team"]["id"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A"])
    args = ap.parse_args()

    session = _session()
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    cur.execute(CANDIDATES_SQL, (args.league,))
    candidates = cur.fetchall()
    print(f"{len(candidates)} {args.league} matches with a recorded red card\n")

    season_labels = sorted({row[8] for row in candidates})
    print(f"building fixture lookup for seasons: {season_labels}\n")
    fixture_lookup = build_fixture_lookup(cur, session, args.league, season_labels)
    conn.commit()  # resolve_team_id may have created/updated team rows

    dc, meta = fit_dixon_coles(cur, args.league)
    print(f"fitted on {meta['n_matches']} matches\n")

    usable, skipped_multi, skipped_range, skipped_nodata, skipped_nomatch = 0, 0, 0, 0, 0
    sum_actual_down = sum_expected_down = 0.0
    sum_actual_up = sum_expected_up = 0.0
    backtest_rows = []

    for i, (match_id, date, home_id, away_id, home, away, hg, ag, _label) in enumerate(candidates, start=1):
        fx = fixture_lookup.get((home_id, away_id, date))
        if fx is None:
            skipped_nomatch += 1
            continue
        fixture_id, home_api, away_api = fx
        try:
            red_cards = fetch_red_cards(session, fixture_id)
        except Exception:
            skipped_nodata += 1
            continue
        if len(red_cards) != 1:
            skipped_multi += 1
            continue
        minute, team_api_id = red_cards[0]
        if not (10 <= minute <= 80):
            skipped_range += 1
            continue

        if team_api_id == home_api:
            down_is_home = True
        elif team_api_id == away_api:
            down_is_home = False
        else:
            skipped_nodata += 1
            continue

        try:
            lam, mu, _rho = dc.rates(home, away)
        except KeyError:
            continue
        remaining = max(90 - minute, 1) / 90.0
        down_rate = lam if down_is_home else mu
        up_rate = mu if down_is_home else lam
        expected_down = down_rate * remaining
        expected_up = up_rate * remaining

        cur.execute(
            """SELECT team_id, COUNT(*) FROM futbol.shots
               WHERE match_id = %s AND result = 'Goal' AND minute > %s
               GROUP BY team_id""", (match_id, minute))
        by_team = dict(cur.fetchall())
        down_team_id = home_id if down_is_home else away_id
        up_team_id = away_id if down_is_home else home_id
        actual_down = by_team.get(down_team_id, 0)
        actual_up = by_team.get(up_team_id, 0)

        sum_actual_down += actual_down
        sum_expected_down += expected_down
        sum_actual_up += actual_up
        sum_expected_up += expected_up
        usable += 1

        cur.execute(
            """SELECT COUNT(*) FILTER (WHERE team_id = %s),
                      COUNT(*) FILTER (WHERE team_id = %s)
               FROM futbol.shots WHERE match_id = %s AND result = 'Goal' AND minute <= %s""",
            (home_id, away_id, match_id, minute))
        h_now, a_now = cur.fetchone()
        actual_outcome = 0 if hg > ag else (1 if hg == ag else 2)
        p_no_adj = inplay_win_probs(lam, mu, h_now, a_now, minute)
        backtest_rows.append((p_no_adj, down_is_home, h_now, a_now, minute,
                              lam, mu, actual_outcome))

        if i % 50 == 0:
            print(f"  ...{i}/{len(candidates)} checked")

    print(f"\nusable matches: {usable} (skipped: {skipped_nomatch} no fixture match, "
          f"{skipped_multi} multi-red, {skipped_range} outside 10-80', "
          f"{skipped_nodata} no data)\n")

    if usable == 0 or sum_expected_down < 1e-6 or sum_expected_up < 1e-6:
        print("Not enough usable matches to calibrate.")
        return

    down_factor = sum_actual_down / sum_expected_down
    up_factor = sum_actual_up / sum_expected_up
    print(f"--- Empirical red-card multipliers ({args.league}) ---")
    print(f"Down-team (10 men): expected {sum_expected_down:.1f} remaining goals, "
          f"actually scored {sum_actual_down:.0f} -> factor {down_factor:.3f}")
    print(f"Up-team (11 v 10):  expected {sum_expected_up:.1f} remaining goals, "
          f"actually scored {sum_actual_up:.0f} -> factor {up_factor:.3f}\n")

    # In-sample backtest: does applying these factors actually improve
    # RPS on the same red-card matches, vs. the unadjusted (factor=1.0)
    # in-play probability? NOT an out-of-sample test -- the factors
    # were derived from this same match set, a real limitation stated
    # here rather than presented as proof it generalizes.
    rps_no_adj, rps_adj = [], []
    for p_no_adj, down_is_home, h_now, a_now, minute, lam, mu, actual in backtest_rows:
        remaining = max(90 - minute, 1) / 90.0
        lam_adj = lam * (down_factor if down_is_home else up_factor)
        mu_adj = mu * (up_factor if down_is_home else down_factor)
        p_adj = inplay_win_probs(lam_adj, mu_adj, h_now, a_now, minute)
        rps_no_adj.append(rps(list(p_no_adj), actual))
        rps_adj.append(rps(list(p_adj), actual))

    print(f"--- In-sample check: does the adjustment help on these same matches? ---")
    print(f"RPS without adjustment: {np.mean(rps_no_adj):.4f}")
    print(f"RPS WITH adjustment:    {np.mean(rps_adj):.4f}")
    delta = (np.mean(rps_no_adj) - np.mean(rps_adj)) / np.mean(rps_no_adj) * 100
    print(f"delta: {delta:+.2f}% ({'improvement' if delta > 0 else 'regression'})")
    print("\nNOTE: in-sample only (factors derived from these same matches) -- "
          "a real out-of-sample check needs a train/test split across more "
          "red-card matches than one league currently has. Treat this as a "
          "sanity check, not proof the factor generalizes.")

    conn.close()


if __name__ == "__main__":
    main()
