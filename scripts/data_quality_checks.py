"""
Data-quality assertions against the live DB -- the class of check that
would have caught the duplicate-teams bug (silent rot, not a crash).
Exits non-zero if anything fails, so it's safe to wire into the nightly
run and treat like any other step that can fail a job.

Posts to ntfy if NTFY_URL is set (e.g. https://ntfy.sh/your-topic or a
self-hosted instance's topic URL); otherwise just prints and exits
non-zero. NTFY_URL is intentionally not defaulted to any real server --
set it in the environment wherever this actually runs.

    python scripts/data_quality_checks.py
"""
import os
import sys

import psycopg2
import psycopg2.extras
import requests

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
NTFY_URL = os.environ.get("NTFY_URL")


def check_corners_in_range(cur) -> list[str]:
    cur.execute(
        """SELECT match_id, team_id, corners FROM futbol.team_match_stats
           WHERE corners IS NOT NULL AND (corners < 0 OR corners > 30)"""
    )
    rows = cur.fetchall()
    return [f"corners={r['corners']} out of [0,30] (match_id={r['match_id']}, team_id={r['team_id']})"
            for r in rows]


def check_possession_sums_to_100(cur, tolerance: float = 2.0) -> list[str]:
    cur.execute(
        """SELECT match_id, SUM(possession_pct) AS total
           FROM futbol.team_match_stats
           WHERE possession_pct IS NOT NULL
           GROUP BY match_id
           HAVING COUNT(*) = 2 AND abs(SUM(possession_pct) - 100) > %s""",
        (tolerance,))
    rows = cur.fetchall()
    return [f"possession sums to {r['total']} (match_id={r['match_id']})" for r in rows]


def check_final_matches_have_goals(cur) -> list[str]:
    cur.execute(
        """SELECT match_id FROM futbol.matches
           WHERE status = 'final' AND (home_score IS NULL OR away_score IS NULL)"""
    )
    rows = cur.fetchall()
    return [f"match_id={r['match_id']} is final with a NULL goals value" for r in rows]


def check_final_matches_have_team_stats(cur) -> list[str]:
    # WC is deliberately excluded -- it was never scraped for corners/shots/
    # etc. (PROPS_LEAGUES in generate_slate.py doesn't include it, only
    # 1X2/BTTS/TOTAL_GOALS are predicted for it), confirmed against live
    # data: all 94 pre-fix violations were WC, zero from EPL/SERIE_A/MLS.
    cur.execute(
        """SELECT m.match_id FROM futbol.matches m
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE m.status = 'final' AND l.code != 'WC'
             AND (SELECT COUNT(*) FROM futbol.team_match_stats ts WHERE ts.match_id = m.match_id) < 2"""
    )
    rows = cur.fetchall()
    return [f"match_id={r['match_id']} is final with fewer than 2 team_match_stats rows" for r in rows]


CHECKS = [
    ("corners in [0,30]", check_corners_in_range),
    ("possession sums to ~100", check_possession_sums_to_100),
    ("final matches have goals", check_final_matches_have_goals),
    ("final matches have team stats", check_final_matches_have_team_stats),
]


def main():
    conn = psycopg2.connect(DSN, cursor_factory=psycopg2.extras.RealDictCursor)
    failures: dict[str, list[str]] = {}
    try:
        with conn.cursor() as cur:
            for name, check in CHECKS:
                violations = check(cur)
                if violations:
                    failures[name] = violations
    finally:
        conn.close()

    if not failures:
        print("data_quality_checks: all clear.")
        return

    lines = [f"data_quality_checks: {sum(len(v) for v in failures.values())} violation(s) "
             f"across {len(failures)} check(s):"]
    for name, violations in failures.items():
        lines.append(f"  [{name}] {len(violations)} violation(s), e.g.:")
        for v in violations[:3]:
            lines.append(f"    - {v}")
    message = "\n".join(lines)
    print(message, file=sys.stderr)

    if NTFY_URL:
        try:
            requests.post(NTFY_URL, data=message.encode("utf-8"), timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"(also failed to notify ntfy: {e})", file=sys.stderr)

    sys.exit(1)


if __name__ == "__main__":
    main()
