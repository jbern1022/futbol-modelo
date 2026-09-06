"""
NBA player points props -- a rolling average over each player's own
recent games, not a trained/fitted model like the other match models
in this project. Mirrors generate_slate.py's current_form() pattern
(a live SQL rolling window computed at slate-generation time) rather
than props.py's LightGBM approach -- points-per-game has a much more
direct, low-noise relationship to recent history than soccer's counting
stats, and a simple baseline is the honest place to start a brand new
market rather than reaching for a heavier model on day one.

No real market line exists (same gap as team TOTAL_POINTS) -- candidate
lines are spaced around the rolling average in units of the player's
own rolling standard deviation (not a fixed point offset, since a
low-usage bench player's game-to-game variance is nothing like a star's),
and only the ones landing in a confident band get published.
"""
from __future__ import annotations

from datetime import datetime

from scipy.stats import norm

MIN_GAMES = 5          # fewer than this and recent history is too thin to trust
ROLLING_WINDOW = 10     # most recent N games
MIN_MINUTES_AVG = 15.0  # excludes deep-bench players with erratic, low-signal minutes
FALLBACK_SIGMA = 6.0    # floor for a player whose recent scoring is oddly steady

ROLLING_POINTS_SQL = """
SELECT pms.points, pms.minutes
FROM futbol.player_match_stats_nba pms
JOIN futbol.matches m ON m.match_id = pms.match_id
WHERE pms.player_id = %s AND m.status = 'final'
  AND m.kickoff_utc < %s
ORDER BY m.kickoff_utc DESC
LIMIT %s
"""

# Rotation players active for an upcoming game are approximated as
# anyone who appeared in the team's last ROSTER_LOOKBACK_GAMES games --
# a GAME-count window, not a calendar-day one. A calendar window (the
# first version of this query used 21 days) breaks at the start of
# every season: the prior season ends in June, the new one starts in
# October, so "the last 21 days" is empty at exactly the moment a
# roster lookup matters most. There's also no cheap, reliable pre-game
# injury/rotation report source wired in yet, so this is a real,
# documented simplification on top of that: a player who's out injured
# but played within the lookback window would incorrectly still be
# considered "active" until enough missed games age them out.
ROSTER_LOOKBACK_GAMES = 15

RECENT_ROSTER_SQL = """
SELECT DISTINCT pms.player_id, p.full_name
FROM futbol.player_match_stats_nba pms
JOIN futbol.players p ON p.player_id = pms.player_id
WHERE pms.match_id IN (
    SELECT m.match_id FROM futbol.matches m
    WHERE (m.home_team_id = %s OR m.away_team_id = %s)
      AND m.status = 'final' AND m.kickoff_utc < %s
    ORDER BY m.kickoff_utc DESC LIMIT %s
)
AND pms.team_id = %s
"""


def rolling_points_stats(cur, player_id: int, before: datetime) -> dict | None:
    """None if the player doesn't have enough recent, meaningful-minutes
    history to make a real claim about -- not every rostered player
    should get a points prediction."""
    cur.execute(ROLLING_POINTS_SQL, (player_id, before, ROLLING_WINDOW))
    rows = cur.fetchall()
    if len(rows) < MIN_GAMES:
        return None
    points = [r[0] for r in rows]
    minutes = [r[1] for r in rows]
    avg_minutes = sum(minutes) / len(minutes)
    if avg_minutes < MIN_MINUTES_AVG:
        return None
    avg_points = sum(points) / len(points)
    variance = sum((p - avg_points) ** 2 for p in points) / len(points)
    sigma = max(variance ** 0.5, FALLBACK_SIGMA)
    return {"avg_points": avg_points, "sigma": sigma, "n_games": len(rows)}


def prob_over(avg_points: float, sigma: float, line: float) -> float:
    return float(1 - norm.cdf(line, loc=avg_points, scale=sigma))


def candidate_lines(avg_points: float, sigma: float,
                    z_offsets: tuple[float, ...] = (-0.7, -0.4, 0.4, 0.7)) -> list[float]:
    """Half-point lines spaced in units of the player's OWN rolling
    sigma, not a fixed point value -- a bench player's 8-point-per-game
    average with sigma=4 and a star's 28-point average with sigma=9
    need very differently sized offsets to produce genuinely confident
    (not just numerically large) candidate lines."""
    lines = []
    for z in z_offsets:
        raw = avg_points + z * sigma
        line = round(raw * 2) / 2
        if line == round(line):  # never a whole number (avoids a push)
            line += 0.5
        if line > 0:  # a negative points line is meaningless
            lines.append(line)
    return lines
