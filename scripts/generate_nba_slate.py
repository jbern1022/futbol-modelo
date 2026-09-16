"""
NBA slate generator -- the vertical-slice equivalent of
generate_nfl_slate.py for NBA: TOTAL_POINTS and PLAYER_POINTS, the two
markets the scope-guard ticket actually asks for. Reuses
build_slate()/persist_slate()/log_degenerate_candidates() from
src/predictions/generator.py unchanged.

    python scripts/generate_nba_slate.py --season 2026-27 --days-ahead 14

Unlike NFL/soccer, there's no free real market line for NBA at all
(nba_api carries no bookmaker data) -- both markets evaluate several
candidate lines spaced around a prediction and only publish the ones
landing in a genuinely confident band, exactly like generate_slate.py's
corners/SOT treatment (same PROPS_OVER_BAND/PROPS_UNDER_BAND
thresholds). See nba_power_ratings.py's candidate_lines() and
nba_player_points.py's candidate_lines().
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd
import psycopg2

from models.nba_player_points import (RECENT_ROSTER_SQL, ROSTER_LOOKBACK_GAMES,
                                       candidate_lines as player_candidate_lines,
                                       prob_over as player_prob_over, rolling_points_stats)
from models.nba_power_ratings import NBAPowerRatings
from predictions.generator import (Inference, build_slate, log_degenerate_candidates,
                                   persist_slate, TARGET_BAND)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Same thresholds generate_slate.py's build_props_inferences() already
# uses for corners/SOT -- one confidence bar for every count-based
# market this project self-generates a line for, soccer or NBA.
PROPS_OVER_BAND = (0.55, 0.80)
PROPS_UNDER_BAND = (0.20, 0.45)

TRAINING_SQL = """
SELECT th.name AS home, ta.name AS away, m.home_score, m.away_score
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = 'NBA' AND m.status = 'final'
  AND s.label IN %s
"""

UPCOMING_SQL = """
SELECT m.match_id, th.name AS home, ta.name AS away, m.kickoff_utc,
       m.home_team_id, m.away_team_id
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
LEFT JOIN futbol.predictions p ON p.match_id = m.match_id
WHERE l.code = 'NBA' AND s.label = %s
  AND m.status = 'scheduled'
  AND m.kickoff_utc BETWEEN now() AND now() + (%s || ' days')::interval
  AND p.prediction_id IS NULL
GROUP BY m.match_id, th.name, ta.name, m.kickoff_utc, m.home_team_id, m.away_team_id
ORDER BY m.kickoff_utc
"""


def _prior_season_label(season: str) -> str:
    """'2026-27' -> '2025-26' -- nba_api's own season label format."""
    start_year = int(season.split("-")[0])
    prior_start = start_year - 1
    return f"{prior_start}-{str(prior_start + 1)[-2:]}"


def fit_model(cur, season: str) -> tuple[NBAPowerRatings, dict]:
    """Trains on last season plus any completed games from the current
    one -- mirrors the NFL cold-start approach: week/game 1 of a new
    season has zero within-season games to fit on."""
    seasons = (_prior_season_label(season), season)
    cur.execute(TRAINING_SQL, (seasons,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["home", "away", "home_score", "away_score"])
    model = NBAPowerRatings(alpha=5.0).fit(df)
    meta = {"alpha": 5.0, "n_games": len(df), "seasons": seasons}
    return model, meta


def build_player_candidates(cur, team_id: int, kickoff: datetime) -> list[Inference]:
    cur.execute(RECENT_ROSTER_SQL, (team_id, team_id, kickoff, ROSTER_LOOKBACK_GAMES, team_id))
    candidates = []
    for player_id, player_name in cur.fetchall():
        stats = rolling_points_stats(cur, player_id, kickoff)
        if stats is None:
            continue
        context = {"avg_points": stats["avg_points"], "sigma": stats["sigma"],
                  "n_games": stats["n_games"]}
        for line in player_candidate_lines(stats["avg_points"], stats["sigma"]):
            p = player_prob_over(stats["avg_points"], stats["sigma"], line)
            if PROPS_OVER_BAND[0] <= p <= PROPS_OVER_BAND[1]:
                candidates.append(Inference("PLAYER_POINTS", f"{player_name} over {line}",
                                            line, "over", p, subject_player_id=player_id,
                                            context=context))
            elif PROPS_UNDER_BAND[0] <= p <= PROPS_UNDER_BAND[1]:
                candidates.append(Inference("PLAYER_POINTS", f"{player_name} under {line}",
                                            line, "under", 1 - p, subject_player_id=player_id,
                                            context=context))
    return candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True, help="e.g. 2026-27")
    ap.add_argument("--days-ahead", type=int, default=14)
    args = ap.parse_args()
    from ops.pipeline_run import track_run, record_model_version_history

    with track_run(f"nba_slate:{args.season}") as set_rows_written:
        conn = psycopg2.connect(DSN)
        written = 0
        with conn.cursor() as cur:
            model, meta = fit_model(cur, args.season)
            print(f"Fit on {meta['n_games']} games from seasons {meta['seasons']}")

            _mv_window = ",".join(meta["seasons"])
            _mv_params = json.dumps({"alpha": meta["alpha"]})
            _mv_metrics = json.dumps({"n_games": meta["n_games"], "sigma_total": model.sigma_total})
            cur.execute(
                """INSERT INTO futbol.model_versions
                     (model_name, version_tag, training_window, params, train_metrics)
                   VALUES ('slate_generator_nba', 'v1', %s, %s, %s)
                   ON CONFLICT (model_name, version_tag) DO UPDATE
                     SET training_window = EXCLUDED.training_window,
                         params = EXCLUDED.params, train_metrics = EXCLUDED.train_metrics
                   RETURNING model_version_id""",
                (_mv_window, _mv_params, _mv_metrics))
            model_version_id = cur.fetchone()[0]
            record_model_version_history(cur, "slate_generator_nba", "v1",
                                          _mv_window, _mv_params, _mv_metrics)
            conn.commit()

            cur.execute(UPCOMING_SQL, (args.season, args.days_ahead))
            fixtures = cur.fetchall()
            print(f"{len(fixtures)} upcoming NBA fixture(s) without a slate "
                 f"(next {args.days_ahead} days)")

            for match_id, home, away, kickoff, home_id, away_id in fixtures:
                try:
                    context = {"predicted_total": model.predicted_total(home, away),
                              "sigma_total": model.sigma_total}
                    candidates = []
                    for line in model.candidate_lines(home, away):
                        p = model.prob_over(home, away, line)
                        if PROPS_OVER_BAND[0] <= p <= PROPS_OVER_BAND[1]:
                            candidates.append(Inference("TOTAL_POINTS", f"Over {line}",
                                                        line, "over", p, context=context))
                        elif PROPS_UNDER_BAND[0] <= p <= PROPS_UNDER_BAND[1]:
                            # Low P(over) is a genuine high-confidence
                            # P(under) claim -- flip it so the ledger
                            # gets under-side calibration support too,
                            # same reasoning as generate_slate.py's props.
                            candidates.append(Inference("TOTAL_POINTS", f"Under {line}",
                                                        line, "under", 1 - p, context=context))

                    candidates += build_player_candidates(cur, home_id, kickoff)
                    candidates += build_player_candidates(cur, away_id, kickoff)

                    candidates = log_degenerate_candidates(cur, match_id, candidates)
                    slate = build_slate(candidates, band=TARGET_BAND, size=20)
                    n = persist_slate(conn, match_id, model_version_id, slate)
                    conn.commit()
                    written += n
                    print(f"  OK {home} vs {away}: {n} predictions written "
                         f"(match_id={match_id})")
                except Exception as e:
                    conn.rollback()
                    print(f"  ERROR {home} vs {away}: {e}")

        conn.close()
        set_rows_written(written)
        print(f"done: {written} total predictions written")


if __name__ == "__main__":
    main()
