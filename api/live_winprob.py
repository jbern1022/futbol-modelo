"""
Query helpers for GET /v1/fixtures/{match_id}/live-winprob (ADR-011 UI).
Lives under api/ rather than src/predictions/ because the API image
ships only api/ and src/ops/ (no scipy), and must not import the live
model itself -- it only reads what scripts/poll_live_winprob.py wrote.
"""
# One point per (minute, score): status.elapsed parks at 45 through
# halftime and at 90 through stoppage, so a match leaves dozens of
# identical-minute ticks. The LAST tick for each keeps the most current
# probability (e.g. a red card mid-stoppage).
LIVE_SERIES_SQL = """
SELECT minute, home_score, away_score, home_win_prob, draw_prob, away_win_prob
FROM (
    SELECT DISTINCT ON (minute, home_score, away_score)
           minute, home_score, away_score, home_win_prob, draw_prob, away_win_prob,
           computed_at
    FROM futbol.live_win_probability
    WHERE match_id = %s
    ORDER BY minute, home_score, away_score, computed_at DESC
) last_tick
ORDER BY computed_at
"""


def live_series(cur, match_id: int) -> list[dict]:
    """The in-play chart's points, oldest first. Works with a tuple or a
    RealDictCursor (the API's pool uses the latter)."""
    cur.execute(LIVE_SERIES_SQL, (match_id,))
    out = []
    for row in cur.fetchall():
        minute, hs, as_, hw, dr, aw = (row.values() if isinstance(row, dict) else row)
        out.append({"minute": minute, "home_score": hs, "away_score": as_,
                    "home": float(hw), "draw": float(dr), "away": float(aw)})
    return out


# Goals and red cards only: own goals are left out (API-Football's team
# attribution for them is unconfirmed -- same call every in-play query
# makes), and the score line still shows them as a jump.
LIVE_EVENTS_SQL = """
SELECT e.minute, e.extra_minute, e.type, e.detail,
       CASE WHEN e.team_id = m.home_team_id THEN 'home' ELSE 'away' END AS side,
       p.full_name AS player
FROM futbol.match_events e
JOIN futbol.matches m ON m.match_id = e.match_id
LEFT JOIN futbol.players p ON p.player_id = e.player_id
WHERE e.match_id = %s
  AND ((e.type = 'Goal' AND e.detail IN ('Normal Goal', 'Penalty'))
       OR (e.type = 'Card' AND e.detail ILIKE '%%red%%'))
ORDER BY e.minute, COALESCE(e.extra_minute, 0)
"""


def live_events(cur, match_id: int) -> list[dict]:
    cur.execute(LIVE_EVENTS_SQL, (match_id,))
    keys = ("minute", "extra_minute", "type", "detail", "side", "player")
    return [dict(row) if isinstance(row, dict) else dict(zip(keys, row))
            for row in cur.fetchall()]
