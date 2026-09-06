"""
NFL player props -- QB passing yards, RB rushing yards. Combines two
real signals rather than a single rolling average (see the design
discussion that preceded this file): a depth-chart gate decides WHO
gets a prediction at all, and a recency-weighted rolling average over
that player's own game log decides the number.

Why both are needed, not just one: a flat rolling average over a
player's last N games (the NBA player-points approach) reacts slowly
to a real role change -- if a starting RB went down in week 6, week 7's
backup would still be diluted by 6 games of bench-level rushing yards
in his own rolling window (or worse, the model would still be trying
to predict the INJURED starter, since a game-count presence check like
NBA's has no way to know he's out). nflverse publishes the actual,
real depth chart every week -- using it to decide who's RB1 this week
is a fact, not an inference from history.

    depth = current_depth_chart(season)
    eligible = depth.get(("BUF", "QB"))   # -> ['00-0034857'] (Josh Allen)
    stats = rolling_yardage_stats(cur, player_id, "rushing_yards", before)
"""
from __future__ import annotations

from datetime import datetime

from scipy.stats import norm

MIN_GAMES = 4           # fewer than this and recency-weighting has nothing to weight
ROLLING_WINDOW = 8       # most recent N games
FALLBACK_SIGMA = 15.0    # floor -- passing/rushing yards are noisier than NBA points
# Exponential recency weights, most recent game first -- roughly halves
# the influence of a game every 2 games back, so a real role or
# game-plan change shows up in 2-3 weeks instead of needing the whole
# rolling window to turn over.
RECENCY_DECAY = 0.75

ROLLING_YARDAGE_SQL = """
SELECT {column}
FROM futbol.player_match_stats_nfl pms
JOIN futbol.matches m ON m.match_id = pms.match_id
WHERE pms.player_id = %s AND m.status = 'final' AND {column} IS NOT NULL
  AND m.kickoff_utc < %s
ORDER BY m.kickoff_utc DESC
LIMIT %s
"""

# depth_team '1' = starter. RB includes '2' as well as '1' -- committee
# backfields are common enough that the primary backup is worth a
# prediction too; QB does not, since an NFL backup QB who actually
# plays meaningful snaps means the starter is hurt (a real, rarer
# in-week event this snapshot won't reliably catch anyway).
DEPTH_RANKS_BY_POSITION = {"QB": ("1",), "RB": ("1", "2")}


def rolling_yardage_stats(cur, player_id: int, column: str, before: datetime) -> dict | None:
    if column not in ("passing_yards", "rushing_yards"):
        raise ValueError(f"unexpected column: {column!r}")
    cur.execute(ROLLING_YARDAGE_SQL.format(column=column), (player_id, before, ROLLING_WINDOW))
    rows = [r[0] for r in cur.fetchall()]
    if len(rows) < MIN_GAMES:
        return None

    weights = [RECENCY_DECAY ** i for i in range(len(rows))]
    total_weight = sum(weights)
    weighted_avg = sum(w * v for w, v in zip(weights, rows)) / total_weight
    weighted_var = sum(w * (v - weighted_avg) ** 2 for w, v in zip(weights, rows)) / total_weight
    sigma = max(weighted_var ** 0.5, FALLBACK_SIGMA)
    return {"avg_yards": weighted_avg, "sigma": sigma, "n_games": len(rows)}


def prob_over(avg_yards: float, sigma: float, line: float) -> float:
    return float(1 - norm.cdf(line, loc=avg_yards, scale=sigma))


def candidate_lines(avg_yards: float, sigma: float,
                    z_offsets: tuple[float, ...] = (-0.7, -0.4, 0.4, 0.7)) -> list[float]:
    """Half-point lines in units of the player's OWN rolling sigma --
    same reasoning as nba_player_points.py's candidate_lines()."""
    lines = []
    for z in z_offsets:
        raw = avg_yards + z * sigma
        line = round(raw * 2) / 2
        if line == round(line):
            line += 0.5
        if line > 0:
            lines.append(line)
    return lines


def current_depth_chart(season: int) -> dict[tuple[str, str], list[str]]:
    """(team_abbr, position) -> [nfl_player_id, ...] at the ranks that
    matter for this project's two markets.

    nfl_data_py returns two genuinely different shapes depending on the
    season: a completed season gets the archived weekly format (season,
    week, club_code, position, depth_team); the CURRENT/upcoming season
    -- exactly the case that matters for generating real predictions --
    gets a live, continuously-scraped snapshot instead (dt, team,
    pos_abb, pos_rank, no week column at all). Verified directly: pulling
    season=2026 before that season has a single game played returns the
    live-snapshot shape. Both are handled here rather than assuming the
    archived shape and silently returning nothing for the season this
    is actually needed for."""
    import nfl_data_py as nfl
    df = nfl.import_depth_charts([season])

    if "week" in df.columns:
        df = df[df["week"] == df["week"].max()]
        team_col, position_col, rank_col = "club_code", "position", "depth_team"
    else:
        # The live snapshot format repeats every past scrape (a new "dt"
        # each time nflverse re-scraped) in the same dataframe -- found
        # by inspecting real output: Josh Allen's own row appeared over
        # 300 times for one team/position before this filter was added.
        df = df[df["dt"] == df["dt"].max()]
        team_col, position_col, rank_col = "team", "pos_abb", "pos_rank"

    chart: dict[tuple[str, str], list[str]] = {}
    for _, row in df.iterrows():
        position = row[position_col]
        ranks = DEPTH_RANKS_BY_POSITION.get(position)
        if ranks is None or str(row[rank_col]) not in ranks or not row["gsis_id"]:
            continue
        key = (row[team_col], position)
        chart.setdefault(key, []).append(row["gsis_id"])
    return chart
