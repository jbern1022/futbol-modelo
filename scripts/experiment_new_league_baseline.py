"""
Does the production Dixon-Coles setup work on a league we don't track yet?

Reads a league's results straight from API-Football (regular-season rounds
only, so relegation play-offs are excluded), then fits production-settings
Dixon-Coles (xi/reg from dc_fit_settings, goals-only) weekly walk-forward and
scores each holdout season against the league-average outcome rates, paired,
with bootstrap 95% CIs. Offline: no database access, nothing is written
except the results cache. Scores only; no xG, no odds.

    python scripts/experiment_new_league_baseline.py --league-id 78 --first-season 2021 --holdouts 2023 2024 2025
    (API-Football ids: Bundesliga 78, Ligue 1 61, Eredivisie 88)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

import numpy as np
import pandas as pd
from dixon_coles import DixonColes
from experiment_dc_ridge import ci
from experiment_dynamic_ratings import probs_from_rates
from ingestion.api_football import _get, _session
from models.dc_settings import dc_fit_settings
from train_dixon_coles import rps


def load_results(league_id: int, seasons: list[int], cache: str) -> pd.DataFrame:
    if os.path.exists(cache):
        raw = json.load(open(cache))
    else:
        session = _session()
        raw = {str(y): _get(session, "fixtures", {"league": league_id, "season": y, "status": "FT"})
               for y in seasons}
        json.dump(raw, open(cache, "w"))
    rows = [dict(season=int(y), date=pd.Timestamp(f["fixture"]["date"][:10]),
                 home=f["teams"]["home"]["name"], away=f["teams"]["away"]["name"],
                 hg=f["goals"]["home"], ag=f["goals"]["away"])
            for y, fx in raw.items() for f in fx
            if f["league"]["round"].startswith("Regular Season")]
    df = pd.DataFrame(rows).dropna().sort_values("date").reset_index(drop=True)
    df[["hg", "ag"]] = df[["hg", "ag"]].astype(int)
    return df


def outcome(hg: int, ag: int) -> int:
    return 0 if hg > ag else (1 if hg == ag else 2)


def run(df: pd.DataFrame, holdout: int) -> None:
    hist, cur = df[df.season < holdout], df[df.season == holdout]
    base = np.array([np.mean(hist.hg > hist.ag), np.mean(hist.hg == hist.ag), np.mean(hist.hg < hist.ag)])
    r_dc, r_nv, l_dc, l_nv, probs, actual = [], [], [], [], [], []
    skipped, refit_at, model = 0, None, None
    for row in cur.itertuples():
        if refit_at is None or row.date >= refit_at:
            past = pd.concat([hist, cur[cur.date < row.date]])
            xi, reg = dc_fit_settings(len(past))
            model = DixonColes(xi=xi).fit(past[["date", "home", "away", "hg", "ag"]], reg=reg)
            refit_at = row.date + timedelta(days=7)
        try:
            lam, mu, rho = model.rates(row.home, row.away)
        except KeyError:
            skipped += 1
            continue
        p, a = probs_from_rates(lam, mu, rho), outcome(row.hg, row.ag)
        r_dc.append(rps(p, a))
        r_nv.append(rps(base, a))
        l_dc.append(-np.log(max(p[a], 1e-9)))
        l_nv.append(-np.log(max(base[a], 1e-9)))
        probs.append(p)
        actual.append(a)
    r_dc, r_nv, l_dc, l_nv = map(np.array, (r_dc, r_nv, l_dc, l_nv))
    d, dl = r_dc - r_nv, l_dc - l_nv
    print(f"\nHoldout {holdout}: {len(r_dc)} scored, {skipped} skipped (team unseen in history)")
    print(f"  RPS  naive {r_nv.mean():.4f}  DC {r_dc.mean():.4f}  diff {d.mean():+.4f}  "
          f"95% CI [{ci(d)[0]:+.4f}, {ci(d)[1]:+.4f}]")
    print(f"  LL   naive {l_nv.mean():.4f}  DC {l_dc.mean():.4f}  diff {dl.mean():+.4f}  "
          f"95% CI [{ci(dl)[0]:+.4f}, {ci(dl)[1]:+.4f}]")
    print(f"  mean predicted H/D/A {np.array(probs).mean(0).round(3).tolist()}  "
          f"realized {[round(float(np.mean(np.array(actual) == k)), 3) for k in range(3)]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", type=int, required=True, help="API-Football league id")
    ap.add_argument("--first-season", type=int, required=True, help="start year of the first season to load")
    ap.add_argument("--holdouts", nargs="+", type=int, required=True, help="start years to score")
    ap.add_argument("--cache", help="results cache path (default /tmp/league_<id>_results.json)")
    args = ap.parse_args()
    seasons = list(range(args.first_season, max(args.holdouts) + 1))
    df = load_results(args.league_id, seasons, args.cache or f"/tmp/league_{args.league_id}_results.json")
    print("matches per season:", df.groupby("season").size().to_dict())
    for y, g in df.groupby("season"):
        print(f"  {y}: goals/game {(g.hg + g.ag).mean():.2f}  home {np.mean(g.hg > g.ag):.3f}  "
              f"draw {np.mean(g.hg == g.ag):.3f}  away {np.mean(g.hg < g.ag):.3f}")
    for h in args.holdouts:
        run(df, h)


if __name__ == "__main__":
    main()
