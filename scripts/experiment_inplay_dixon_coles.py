"""
Todoist: "futbol-modelo: in-play/live win-probability updates" (Phase 3).
OFFLINE VALIDATION ONLY, per explicit direction (2026-09-30): no live
polling, no new tables, no UI -- just answering "is a conditioned-
Dixon-Coles in-play probability even well-calibrated" before any live
infrastructure gets built.

Key finding this validates: a live win-probability does NOT need "a
different model class" (the ticket's own assumption) -- Dixon-Coles
already fits per-team goal rates (lam, mu) for a full match. Re-deriving
a scoreline distribution for the REMAINING time (rates scaled by
remaining_minutes/90), then combining with the current score, gives an
in-play probability using the exact same fitted model, no new
architecture.

Proxy for real live score trajectories (no minute-by-minute history is
stored anywhere in this project yet, live or otherwise): `shots` has
real goal-minute data from Understat (EPL/SERIE_A/LA_LIGA); MLS has no
Understat coverage, so it uses `match_events` (API-Football's
/fixtures/events, scripts/backfill_match_events.py) instead -- same
role, different source. Reconstructs
each holdout match's TRUE running score at fixed checkpoints (15', 30',
45', 60', 75') from real historical goal events, then checks whether
the conditioned in-play probability at that checkpoint is well-
calibrated against the REAL final outcome -- and whether it actually
beats just using the static pre-match probability unchanged (the real
question: does conditioning on the live score add value at all).

    python scripts/experiment_inplay_dixon_coles.py --league EPL --holdout 2025-26
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
import psycopg2
from scipy.stats import poisson

from dixon_coles import DixonColes, derive_markets
from train_dixon_coles import Q as MATCHES_Q, rps  # noqa: E402

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
CHECKPOINTS = [15, 30, 45, 60, 75]
MAX_GOALS = 10

GOALS_Q_SHOTS = """
SELECT s.match_id, s.team_id, s.minute
FROM futbol.shots s
JOIN futbol.matches m ON m.match_id = s.match_id
JOIN futbol.seasons se ON se.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = se.league_id
WHERE l.code = %s AND s.result = 'Goal' AND s.minute IS NOT NULL
ORDER BY s.match_id, s.minute;
"""

# MLS has no Understat shots coverage -- uses match_events (API-Football,
# scripts/backfill_match_events.py) instead. 'Normal Goal'/'Penalty'
# only -- 'Missed Penalty' is an event marker, not a scored goal, and
# 'Own Goal' is excluded (team attribution not yet confirmed either way,
# same conservative call the shots-based query makes).
GOALS_Q_EVENTS = """
SELECT e.match_id, e.team_id, e.minute
FROM futbol.match_events e
JOIN futbol.matches m ON m.match_id = e.match_id
JOIN futbol.seasons se ON se.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = se.league_id
WHERE l.code = %s AND e.type = 'Goal' AND e.detail IN ('Normal Goal', 'Penalty')
ORDER BY e.match_id, e.minute;
"""

GOALS_SOURCE = {"EPL": GOALS_Q_SHOTS, "SERIE_A": GOALS_Q_SHOTS,
                "LA_LIGA": GOALS_Q_SHOTS, "MLS": GOALS_Q_EVENTS}


def inplay_probs(lam: float, mu: float, rho: float, h_now: int, a_now: int,
                 minute: int, use_rho: bool = True) -> list[float]:
    """1X2 probabilities conditioned on the current score at `minute`,
    derived from the SAME fitted pre-match lam/mu/rho -- no new model.
    Scales the remaining-time goal expectation by the fraction of the
    match left, builds a small scoreline matrix for ADDITIONAL goals
    only, then combines with the already-banked h_now/a_now lead."""
    remaining = max(90 - minute, 1) / 90.0
    lam_r, mu_r = lam * remaining, mu * remaining
    hp = poisson.pmf(np.arange(MAX_GOALS + 1), lam_r)
    ap = poisson.pmf(np.arange(MAX_GOALS + 1), mu_r)
    m = np.outer(hp, ap)
    # Dixon-Coles' low-score correction was fit for a full 90' match,
    # applying it to a shorter remaining-time sub-match is an
    # approximation (real limitation, stated in the report below) --
    # applied anyway since it only meaningfully touches the 0-0/1-0/0-1/
    # 1-1 cells, which still make sense as "additional goals" outcomes.
    if use_rho:
        for x in range(2):
            for y in range(2):
                tau = 1.0
                if x == 0 and y == 0:
                    tau = 1 - lam_r * mu_r * rho
                elif x == 0 and y == 1:
                    tau = 1 + lam_r * rho
                elif x == 1 and y == 0:
                    tau = 1 + mu_r * rho
                elif x == 1 and y == 1:
                    tau = 1 - rho
                m[x, y] *= max(tau, 0)
    m = m / m.sum()

    i, j = np.indices(m.shape)
    final_h = h_now + i
    final_a = a_now + j
    return [float(m[final_h > final_a].sum()),
            float(m[final_h == final_a].sum()),
            float(m[final_h < final_a].sum())]


def reconstruct_trajectories(goals_df: pd.DataFrame, home_id: int, away_id: int) -> dict:
    """Real running score at each checkpoint minute, from real goal events."""
    hg = sorted(goals_df.loc[goals_df.team_id == home_id, "minute"])
    ag = sorted(goals_df.loc[goals_df.team_id == away_id, "minute"])
    out = {}
    for cp in CHECKPOINTS:
        out[cp] = (sum(1 for m in hg if m <= cp), sum(1 for m in ag if m <= cp))
    return out


def main():
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
        """SELECT m.match_id, m.home_team_id, m.away_team_id,
                  th.name, ta.name, m.kickoff_utc::date
           FROM futbol.matches m
           JOIN futbol.teams th ON th.team_id = m.home_team_id
           JOIN futbol.teams ta ON ta.team_id = m.away_team_id
           JOIN futbol.seasons s ON s.season_id = m.season_id
           JOIN futbol.leagues l ON l.league_id = s.league_id
           WHERE l.code = %s AND m.status = 'final'""", (args.league,))
    # Keyed on (home, away, date) -- matches train_dixon_coles.py's own
    # query shape exactly, so this lookup can't silently mismatch a
    # team pair that played each other twice in different seasons.
    match_lookup = {(h, a, d): (mid, hid, aid) for mid, hid, aid, h, a, d in cur.fetchall()}

    goals = pd.read_sql(GOALS_SOURCE[args.league], conn, params=(args.league,))
    conn.close()
    print(f"loaded {len(matches)} finals, {len(goals)} real goal events for {args.league}\n")

    train = matches[matches.season != args.holdout]
    test = matches[matches.season == args.holdout]
    dc = DixonColes(xi=args.xi).fit(
        train.rename(columns=str).assign(date=pd.to_datetime(train.date)))
    print(f"fitted on {len(train)} matches, testing {len(test)} in holdout {args.holdout}\n")

    # Per-checkpoint scoring: conditioned-in-play vs static pre-match vs
    # in-play-without-rho (ablation -- is the low-score correction,
    # fit for a full 90', actually pulling its weight on a shortened
    # remaining-time window, or just adding noise?).
    by_cp: dict[int, dict] = {cp: {"inplay_rps": [], "static_rps": [], "norho_rps": [],
                                   "inplay_ll": [], "static_ll": [], "norho_ll": []}
                              for cp in CHECKPOINTS}

    n_matches_used = 0
    for _, row in test.iterrows():
        key = (row.home, row.away, row.date.date())
        if key not in match_lookup:
            continue
        match_id, home_id, away_id = match_lookup[key]
        mgoals = goals[goals.match_id == match_id]
        if mgoals.empty and (row.hg + row.ag) > 0:
            continue  # goals happened but no minute data -- skip, don't fake a 0-0 trajectory

        try:
            lam, mu, rho = dc.rates(row.home, row.away)
        except KeyError:
            continue
        static_p = derive_markets(dc.predict(row.home, row.away))
        static_vec = [static_p["home_win"], static_p["draw"], static_p["away_win"]]
        actual = 0 if row.hg > row.ag else (1 if row.hg == row.ag else 2)

        traj = reconstruct_trajectories(mgoals, home_id, away_id)
        n_matches_used += 1
        for cp in CHECKPOINTS:
            h_now, a_now = traj[cp]
            p = inplay_probs(lam, mu, rho, h_now, a_now, cp)
            p_norho = inplay_probs(lam, mu, rho, h_now, a_now, cp, use_rho=False)
            by_cp[cp]["inplay_rps"].append(rps(p, actual))
            by_cp[cp]["static_rps"].append(rps(static_vec, actual))
            by_cp[cp]["norho_rps"].append(rps(p_norho, actual))
            by_cp[cp]["inplay_ll"].append(-np.log(max(p[actual], 1e-9)))
            by_cp[cp]["static_ll"].append(-np.log(max(static_vec[actual], 1e-9)))
            by_cp[cp]["norho_ll"].append(-np.log(max(p_norho[actual], 1e-9)))

    print(f"scored {n_matches_used} matches with usable goal-minute data\n")
    print(f"{'minute':>7} | {'in-play RPS':>12} | {'no-rho RPS':>11} | {'static RPS':>11} | "
          f"{'in-play LL':>11} | {'no-rho LL':>10} | {'static LL':>10}")
    for cp in CHECKPOINTS:
        d = by_cp[cp]
        if not d["inplay_rps"]:
            continue
        print(f"{cp:>7} | {np.mean(d['inplay_rps']):>12.4f} | {np.mean(d['norho_rps']):>11.4f} | "
              f"{np.mean(d['static_rps']):>11.4f} | {np.mean(d['inplay_ll']):>11.4f} | "
              f"{np.mean(d['norho_ll']):>10.4f} | {np.mean(d['static_ll']):>10.4f}")

    print("\n--- Verdict ---")
    last_cp = CHECKPOINTS[-1]
    if by_cp[last_cp]["inplay_rps"]:
        improvement = ((np.mean(by_cp[last_cp]["static_rps"]) - np.mean(by_cp[last_cp]["inplay_rps"]))
                      / np.mean(by_cp[last_cp]["static_rps"]) * 100)
        print(f"At minute {last_cp}: in-play conditioning {'improves' if improvement > 0 else 'WORSENS'} "
              f"RPS by {improvement:+.1f}% vs. the static pre-match probability.")
        print("Expect improvement to grow at later checkpoints (more information has arrived) "
              "-- check the table above for that trend, not just the final row.")


if __name__ == "__main__":
    main()
