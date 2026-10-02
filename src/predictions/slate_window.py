"""
The 3-day slate window (ADR-012) -- one rule for every NFL and soccer
slate generator, so a fixture's locked prediction always sees injury,
suspension and depth-chart news from the last few days before kickoff.

Why it's enforced here and not just in cronjobs.yaml: the real incident
(2026-10-02) was a MANUAL generate_nfl_slate.py run on 2026-09-06 that
slated 180 NFL games through December in one batch. The cron's own
--days-ahead was never the problem; nothing stopped a wider hand-run.
clamp_days_ahead() is applied inside every generator, whatever the CLI
says.

"Already slated" means a fixture has at least one prediction that is
NOT voided -- a fixture whose whole slate was voided as stale must be
picked up again by the next run (see scripts/void_stale_slates.py).
"""
from __future__ import annotations

SLATE_WINDOW_DAYS = 3
STALE_SLATE_GRADER_VERSION = "stale-slate-void-1.0"

# A SQL fragment for "this fixture has no live (non-voided) prediction",
# against a matches row aliased as m. Shared by every generator's
# upcoming-fixtures query so they can't drift apart.
NO_LIVE_PREDICTION_SQL = """NOT EXISTS (
      SELECT 1 FROM futbol.predictions lp
      LEFT JOIN futbol.prediction_grades lg ON lg.prediction_id = lp.prediction_id
      WHERE lp.match_id = m.match_id AND lg.outcome IS DISTINCT FROM 'void')"""


def clamp_days_ahead(days: int) -> int:
    if days < 1:
        raise ValueError(f"days ahead must be at least 1, got {days}")
    return min(days, SLATE_WINDOW_DAYS)


def has_live_slate(cur, match_id: int) -> bool:
    cur.execute(
        """SELECT 1 FROM futbol.predictions p
           LEFT JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
           WHERE p.match_id = %s AND g.outcome IS DISTINCT FROM 'void'
           LIMIT 1""", (match_id,))
    return cur.fetchone() is not None


# nflverse weekly-roster status_description_abbr codes -- only the ones
# whose meaning is certain. Anything else on the reserve list is named
# by its raw code rather than guessed at.
_NFL_RESERVE_CODES = {
    "R01": "on Reserve/Injured (IR)",
    "R48": "on Reserve/Injured (IR)",
    "R04": "on Reserve/Physically Unable to Perform (PUP)",
    "R05": "on Reserve/Non-Football Injury (NFI)",
}


def nfl_reserve_reason(status: str, code: str) -> str | None:
    if status != "RES":
        return None
    return _NFL_RESERVE_CODES.get(code, f"on a reserve list (nflverse code {code})")


# API-Football /injuries reasons that are suspensions, not injuries --
# seen in the live player_injuries table.
_SOCCER_SUSPENSION_REASONS = {"Red Card", "Yellow Cards", "Suspended"}


def soccer_absence_reason(reason: str) -> str:
    if reason in _SOCCER_SUSPENSION_REASONS:
        return f"suspended ({reason})"
    return f"out ({reason})"


def stale_void_reason(days_before_kickoff: int, absence: str | None = None) -> str:
    window = (f"Slated {days_before_kickoff} days before kickoff, outside the "
              f"{SLATE_WINDOW_DAYS}-day slate window (ADR-012); superseded by a "
              f"fresh slate.")
    if absence:
        return f"Player {absence}. {window}"
    return window
