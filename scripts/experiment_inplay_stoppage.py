"""
Does the in-play model's remaining-time assumption hold late in a match?

ADR-011's offline validation (scripts/experiment_inplay_dixon_coles.py)
stopped at 75'. Live, the poller reads API-Football's status.elapsed,
which caps at 90 through stoppage time. The model scales the remaining
goal expectation by max(90 - minute, 1) / 90, so all of stoppage counts
as 1 minute. Found 2026-10-02 checking real live series against real
matches: MLS match 4606 sat at 1-1 in stoppage with draw = 0.966, and
the home side scored. Across 4,180 EPL/SERIE_A/LA_LIGA matches, 0.197
goals per match come at minute >= 90 (18.4% of matches have one); the
linear rule allows about 0.03.

Compares two remaining-time rules on the same fitted Dixon-Coles rates,
same holdout season, from 15' through 90':

  linear     max(90 - minute, 1) / 90             (live today)
  empirical  share of goals scored AFTER `minute`, pooled from EPL and
             SERIE_A Understat shots in seasons OTHER than the holdout (no
             holdout leakage). La Liga only has 2025-26 shot data, so for
             La Liga this is a pure out-of-league test of the same curve.

    python scripts/experiment_inplay_stoppage.py --league EPL --holdout 2025-26
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

from dixon_coles import DixonColes
from experiment_inplay_dixon_coles import DSN, GOALS_SOURCE, MAX_GOALS
from train_dixon_coles import Q as MATCHES_Q, rps  # noqa: E402

CHECKPOINTS = [15, 30, 45, 60, 75, 80, 85, 88, 89, 90]


def probs(lam: float, mu: float, h_now: int, a_now: int, remaining: float) -> list[float]:
    """Same scoreline construction as live_winprob.inplay_win_probs (no rho,
    which the live model already dropped per the ADR-011 ablation)."""
    hp = poisson.pmf(np.arange(MAX_GOALS + 1), lam * remaining)
    ap = poisson.pmf(np.arange(MAX_GOALS + 1), mu * remaining)
    m = np.outer(hp, ap)
    m = m / m.sum()
    i, j = np.indices(m.shape)
    fh, fa = h_now + i, a_now + j
    return [float(m[fh > fa].sum()), float(m[fh == fa].sum()), float(m[fh < fa].sum())]


def linear_remaining(minute: int) -> float:
    return max(90 - minute, 1) / 90.0


def empirical_remaining_fn(train_goal_minutes: np.ndarray):
    total = len(train_goal_minutes)

    def f(minute: int) -> float:
        return float((train_goal_minutes > minute).sum()) / total
    return f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["EPL", "SERIE_A", "LA_LIGA", "MLS"])
    ap.add_argument("--holdout", default="2025-26")
    ap.add_argument("--xi", type=float, default=0.0018)
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    matches = pd.read_sql(MATCHES_Q, conn, params=(args.league,))
    matches["date"] = pd.to_datetime(matches["date"])
    cur = conn.cursor()
    cur.execute(
        """SELECT m.match_id, m.home_team_id, m.away_team_id, th.name, ta.name,
                  m.kickoff_utc::date, s.label
           FROM futbol.matches m
           JOIN futbol.teams th ON th.team_id = m.home_team_id
           JOIN futbol.teams ta ON ta.team_id = m.away_team_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = %s AND m.status = 'final'""", (args.league,))
    rows = cur.fetchall()
    match_lookup = {(h, a, d): (mid, hid, aid) for mid, hid, aid, h, a, d, _ in rows}  # noqa: E501
    goals = pd.read_sql(GOALS_SOURCE[args.league], conn, params=(args.league,))
    # Only matches whose event/shot data exists at all. "Has goals but no
    # goal rows -> skip" alone lets every 0-0 match without data through:
    # the first MLS run (2026-10-02) scored 33 "usable" 2025 matches that
    # were exactly that -- MLS 2025 had no match_events yet -- a goalless
    # sample that favors whichever rule expects fewer late goals.
    coverage_table = "match_events" if args.league == "MLS" else "shots"
    covered = set(pd.read_sql(f"SELECT DISTINCT match_id FROM futbol.{coverage_table}", conn).match_id)
    curve_minutes = pd.read_sql(
        """SELECT s.minute FROM futbol.shots s
           JOIN futbol.matches m ON m.match_id = s.match_id
           JOIN futbol.seasons se ON se.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = se.league_id
           WHERE l.code IN ('EPL', 'SERIE_A') AND se.label <> %s
             AND s.result = 'Goal' AND s.minute IS NOT NULL""",
        conn, params=(args.holdout,)).minute.to_numpy()
    conn.close()

    train = matches[matches.season != args.holdout]
    test = matches[matches.season == args.holdout]
    dc = DixonColes(xi=args.xi).fit(train.rename(columns=str).assign(date=pd.to_datetime(train.date)))
    empirical = empirical_remaining_fn(curve_minutes)

    scores: dict[int, dict[str, list[float]]] = {
        cp: {"lin_rps": [], "emp_rps": [], "lin_ll": [], "emp_ll": []} for cp in CHECKPOINTS}
    used = 0
    for _, row in test.iterrows():
        key = (row.home, row.away, row.date.date())
        if key not in match_lookup:
            continue
        match_id, home_id, away_id = match_lookup[key]
        if match_id not in covered:
            continue
        mg = goals[goals.match_id == match_id]
        if mg.empty and (row.hg + row.ag) > 0:
            continue
        try:
            lam, mu, _ = dc.rates(row.home, row.away)
        except KeyError:
            continue
        actual = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)
        hg = mg.loc[mg.team_id == home_id, "minute"].to_numpy()
        ag = mg.loc[mg.team_id == away_id, "minute"].to_numpy()
        used += 1
        for cp in CHECKPOINTS:
            h_now, a_now = int((hg <= cp).sum()), int((ag <= cp).sum())
            for tag, rem in (("lin", linear_remaining(cp)), ("emp", empirical(cp))):
                p = probs(lam, mu, h_now, a_now, rem)
                scores[cp][f"{tag}_rps"].append(rps(p, actual))
                scores[cp][f"{tag}_ll"].append(-np.log(max(p[actual], 1e-9)))

    print(f"{args.league}: fitted on {len(train)}, scored {used} holdout matches ({args.holdout})")
    print(f"{'minute':>6} | {'lin rem':>7} | {'emp rem':>7} | {'lin RPS':>8} | {'emp RPS':>8} | "
          f"{'lin LL':>7} | {'emp LL':>7}")
    for cp in CHECKPOINTS:
        d = scores[cp]
        print(f"{cp:>6} | {linear_remaining(cp):>7.3f} | {empirical(cp):>7.3f} | "
              f"{np.mean(d['lin_rps']):>8.4f} | {np.mean(d['emp_rps']):>8.4f} | "
              f"{np.mean(d['lin_ll']):>7.4f} | {np.mean(d['emp_ll']):>7.4f}")


if __name__ == "__main__":
    main()
