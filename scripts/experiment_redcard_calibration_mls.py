"""
Red-card remaining-time multipliers for MLS, from match_events.

scripts/experiment_redcard_calibration.py calibrated EPL/SERIE_A from
futbol.shots plus one /fixtures/events API call per match, in-sample
only. MLS has no Understat shots, but match_events now holds the full
2025 and 2026 seasons (backfilled 2026-10-02): red-card minute and team
and every goal, with no API calls needed. Two seasons also allow an
OUT-OF-SAMPLE check, which the EPL/SERIE_A factors never had:
calibrate on --calibrate, then score the in-play probability at each
red-card minute on --test, adjusted vs. unadjusted.

Same method otherwise: single-red-card matches, card in minute 10-80,
factor = SUM(actual remaining goals) / SUM(Dixon-Coles expected remaining
goals), remaining time from remaining_share() (MLS is on the empirical
curve, ADR-013). Own goals excluded, as in every in-play query.

    python scripts/experiment_redcard_calibration_mls.py --calibrate 2025 --test 2026
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import psycopg2

from generate_slate import fit_dixon_coles
from predictions.live_winprob import inplay_win_probs, remaining_share
from train_dixon_coles import rps

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
LEAGUE = "MLS"

RED_CARD_MATCHES_SQL = """
SELECT m.match_id, th.name, ta.name, m.home_team_id, m.away_team_id,
       m.home_score, m.away_score, e.minute, e.team_id
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.match_events e ON e.match_id = m.match_id
WHERE l.code = %s AND s.label = %s AND m.status = 'final'
  AND e.type = 'Card' AND e.detail ILIKE '%%red%%'
  AND (SELECT count(*) FROM futbol.match_events r
       WHERE r.match_id = m.match_id AND r.type = 'Card' AND r.detail ILIKE '%%red%%') = 1
  AND e.minute BETWEEN 10 AND 80
"""

GOALS_SQL = """
SELECT team_id, minute FROM futbol.match_events
WHERE match_id = %s AND type = 'Goal' AND detail IN ('Normal Goal', 'Penalty')
"""


def collect(cur, dc, season: str) -> list[dict]:
    cur.execute(RED_CARD_MATCHES_SQL, (LEAGUE, season))
    rows = []
    for match_id, home, away, home_id, away_id, hg, ag, minute, red_team in cur.fetchall():
        try:
            lam, mu, _ = dc.rates(home, away)
        except KeyError:
            continue
        cur.execute(GOALS_SQL, (match_id,))
        goals = cur.fetchall()
        down_is_home = red_team == home_id
        down_id, up_id = (home_id, away_id) if down_is_home else (away_id, home_id)
        rem = remaining_share(minute, LEAGUE)
        rows.append({
            "minute": minute, "down_is_home": down_is_home, "lam": lam, "mu": mu,
            "h_now": sum(1 for t, m in goals if t == home_id and m <= minute),
            "a_now": sum(1 for t, m in goals if t == away_id and m <= minute),
            "actual_down": sum(1 for t, m in goals if t == down_id and m > minute),
            "actual_up": sum(1 for t, m in goals if t == up_id and m > minute),
            "expected_down": (lam if down_is_home else mu) * rem,
            "expected_up": (mu if down_is_home else lam) * rem,
            "outcome": 0 if hg > ag else (1 if hg == ag else 2),
        })
    return rows


def factors(rows: list[dict]) -> tuple[float, float]:
    down = sum(r["actual_down"] for r in rows) / sum(r["expected_down"] for r in rows)
    up = sum(r["actual_up"] for r in rows) / sum(r["expected_up"] for r in rows)
    return down, up


def rps_with(rows: list[dict], down: float, up: float) -> np.ndarray:
    out = []
    for r in rows:
        lam = r["lam"] * (down if r["down_is_home"] else up)
        mu = r["mu"] * (up if r["down_is_home"] else down)
        p = inplay_win_probs(lam, mu, r["h_now"], r["a_now"], r["minute"], league=LEAGUE)
        out.append(rps(list(p), r["outcome"]))
    return np.array(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", required=True)
    ap.add_argument("--test", required=True)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    dc, meta = fit_dixon_coles(cur, LEAGUE)
    cal, test = collect(cur, dc, args.calibrate), collect(cur, dc, args.test)
    conn.close()

    down, up = factors(cal)
    print(f"MLS calibrate {args.calibrate}: {len(cal)} single-red matches (card 10-80')")
    print(f"   down (10 men) {down:.3f}   up (11 v 10) {up:.3f}")
    t_down, t_up = factors(test)
    print(f"   same ratio measured on {args.test} alone ({len(test)} matches): "
          f"down {t_down:.3f}  up {t_up:.3f}")

    base, adj = rps_with(test, 1.0, 1.0), rps_with(test, down, up)
    diff = adj - base
    rng = np.random.default_rng(0)
    boots = [rng.choice(diff, len(diff)).mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"OUT-OF-SAMPLE {args.test}: RPS at the red-card minute, unadjusted {base.mean():.4f} "
          f"-> adjusted {adj.mean():.4f} ({(base.mean() - adj.mean()) / base.mean() * 100:+.1f}%), "
          f"diff {diff.mean():+.4f} 95% CI [{lo:+.4f}, {hi:+.4f}]")
    print(f"   (Dixon-Coles fit: production settings, {meta['n_matches']} matches; "
          f"like the EPL/SERIE_A calibration it includes these seasons' results)")


if __name__ == "__main__":
    main()
