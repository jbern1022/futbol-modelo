"""
ADR-011: in-play win-probability, backend only (no UI yet, per
explicit direction). Meant to run every ~60s (see
k8s/cronjobs.yaml's futbol-live-winprob) -- gated to a near-zero-cost
no-op when nothing in this league could plausibly be live right now,
checked against our own matches table BEFORE ever calling the real
API, so this doesn't burn quota or log noise 23 hours a day.

    python scripts/poll_live_winprob.py --league EPL
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import psycopg2

from generate_slate import fit_dixon_coles
from ingestion.api_football import _get, _session, store_events
from predictions.live_winprob import apply_red_card, inplay_win_probs
from ops.json_logging import configure_json_logging
from ops.pipeline_run import track_run

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# A match kicked off up to this long ago could still plausibly be
# live -- 90' + stoppage/extra time + a safety margin. Anything older
# is assumed finished (it'll simply stop appearing in live=all's
# response once it genuinely ends, so this bound is a cheap
# pre-filter, not the real "is it still live" check).
MAX_MATCH_MINUTES = 130

CANDIDATES_SQL = """
SELECT m.match_id, m.api_football_fixture_id, th.name, ta.name,
       th.api_football_id, ta.api_football_id
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = %s AND m.status = 'scheduled'
  AND m.kickoff_utc <= now()
  AND m.kickoff_utc >= now() - (%s || ' minutes')::interval
  AND m.api_football_fixture_id IS NOT NULL;
"""


def fetch_live_events(session, fixture_id: int) -> list[dict]:
    """
    One /fixtures/events call per currently-live tracked fixture (not
    per tick across everything) -- bounded by how many of our tracked
    leagues have concurrent live matches, same cost shape as the
    live=all call itself. The response feeds both red_card_side() and
    match_events (the in-play chart's goal/card markers).
    """
    try:
        return _get(session, "fixtures/events", {"fixture": fixture_id})
    except Exception:
        return []


def red_card_side(events: list[dict], home_api: int) -> bool | None:
    """None = no red card yet. True/False = home/away team has gone
    down to 10 men."""
    for e in events:
        if e.get("type") == "Card" and "red" in (e.get("detail") or "").lower():
            return e["team"]["id"] == home_api
    return None


def poll_league(cur, session, league: str) -> int:
    cur.execute(CANDIDATES_SQL, (league, MAX_MATCH_MINUTES))
    candidates = cur.fetchall()
    if not candidates:
        return 0

    fixture_to_match = {}
    for match_id, fid, home, away, home_api, away_api in candidates:
        if fid is not None:
            fixture_to_match[fid] = (match_id, home, away, home_api, away_api)

    response = _get(session, "fixtures", {"live": "all"})
    live_by_fixture = {fx["fixture"]["id"]: fx for fx in response}

    matched = {fid: fx for fid, fx in live_by_fixture.items() if fid in fixture_to_match}
    if not matched:
        return 0

    dc, _ = fit_dixon_coles(cur, league)
    written = 0
    for fid, fx in matched.items():
        match_id, home, away, home_api, away_api = fixture_to_match[fid]
        minute = fx["fixture"]["status"]["elapsed"]
        h_now = fx["goals"]["home"]
        a_now = fx["goals"]["away"]
        if minute is None or h_now is None or a_now is None:
            continue
        try:
            lam, mu, _rho = dc.rates(home, away)
        except KeyError:
            continue
        events = fetch_live_events(session, fid)
        if events:
            store_events(cur, match_id, events)
        home_is_down = red_card_side(events, home_api)
        lam, mu = apply_red_card(lam, mu, league, home_is_down)
        home_p, draw_p, away_p = inplay_win_probs(lam, mu, h_now, a_now, minute, league=league)
        cur.execute(
            """INSERT INTO futbol.live_win_probability
                 (match_id, minute, home_score, away_score,
                  home_win_prob, draw_prob, away_win_prob)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (match_id, minute, h_now, a_now,
             round(home_p, 5), round(draw_p, 5), round(away_p, 5)))
        written += 1
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "MLS", "LA_LIGA"])
    args = ap.parse_args()
    log = configure_json_logging(f"live_winprob:{args.league}")

    with track_run(f"live_winprob:{args.league}") as set_rows_written:
        session = _session()
        conn = psycopg2.connect(DSN)
        try:
            with conn.cursor() as cur:
                written = poll_league(cur, session, args.league)
            conn.commit()
        finally:
            conn.close()
        set_rows_written(written)
        log.info("live_winprob tick done", extra={"league": args.league, "n_written": written})


if __name__ == "__main__":
    main()
