"""
NFL slate generator -- the vertical-slice equivalent of generate_slate.py
for NFL: MONEYLINE, SPREAD, TOTAL_POINTS, and player props (QB passing
yards, RB rushing yards + receptions, WR/TE receiving yards + receptions,
anytime-TD for every skill position). Reuses build_slate()/persist_slate()/
log_degenerate_candidates() from src/predictions/generator.py unchanged
-- those are already market/sport-agnostic.

    python scripts/generate_nfl_slate.py --season 2026 --days-ahead 14

Predicts against the real market spread/total lines nfl_data_py already
bundles into the schedule data (spread_line/total_line/*_moneyline) --
free, no separate odds ingestion needed, unlike the MLS/EPL/Serie A
odds-comparison feature which needed a paid API. A game with no
published line yet (sportsbooks don't line every future week
immediately) is simply skipped -- there's nothing to predict against.

Player props have no market line at all (nfl_data_py's schedule data
covers game-level lines only) -- candidate lines are spaced around a
recency-weighted rolling average instead, same self-generated-line
treatment as NBA's player points and totals. WHO gets a prediction is
decided by the real current depth chart (nfl_player_props.py's
current_depth_chart()), not by rolling-stat presence alone -- a flat
history window can't tell a healthy committee back from an injured
starter nearly as fast as this week's actual depth chart can.

The models themselves are NOT calibrated: Normal-approximation
probabilities only, since there's no graded NFL history yet to
calibrate against. Revisit once a real number of weeks have been
graded, same as the corners/SOT calibration fix -- just not possible
on day one for a brand new sport.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import nfl_data_py as nfl
import pandas as pd
import psycopg2

from models.nfl_player_props import candidate_lines as player_candidate_lines
from models.nfl_player_props import current_depth_chart, prob_over as player_prob_over
from models.nfl_player_props import prob_anytime_td as player_prob_anytime_td
from models.nfl_player_props import rolling_td_rate, rolling_yardage_stats
from models.nfl_power_ratings import NFLPowerRatings
from predictions.generator import (Inference, build_slate, log_degenerate_candidates,
                                   persist_slate, TARGET_BAND)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

# Same thresholds generate_slate.py's build_props_inferences() already
# uses for corners/SOT -- one confidence bar for every count-based
# market this project self-generates a line for.
PROPS_OVER_BAND = (0.55, 0.80)
PROPS_UNDER_BAND = (0.20, 0.45)

TRAINING_SQL = """
SELECT th.name AS home, ta.name AS away, m.home_score, m.away_score
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
WHERE l.code = 'NFL' AND m.status = 'final'
  AND s.label IN %s
"""

UPCOMING_SQL = """
SELECT m.match_id, m.external_ref, th.name AS home, ta.name AS away,
       th.team_id AS home_id, ta.team_id AS away_id,
       th.nfl_abbr AS home_abbr, ta.nfl_abbr AS away_abbr, m.kickoff_utc
FROM futbol.matches m
JOIN futbol.teams th ON th.team_id = m.home_team_id
JOIN futbol.teams ta ON ta.team_id = m.away_team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
LEFT JOIN futbol.predictions p ON p.match_id = m.match_id
WHERE l.code = 'NFL' AND s.label = %s
  AND m.status = 'scheduled'
  AND m.kickoff_utc BETWEEN now() AND now() + (%s || ' days')::interval
  AND p.prediction_id IS NULL
GROUP BY m.match_id, m.external_ref, th.name, ta.name, th.team_id, ta.team_id,
         th.nfl_abbr, ta.nfl_abbr, m.kickoff_utc
ORDER BY m.kickoff_utc
"""


def fit_model(cur, season: int) -> tuple[NFLPowerRatings, dict]:
    """Trains on the last two completed seasons plus any completed games
    from the current one -- week 1 of a new season has zero within-season
    games to fit on, so last season's results are the only real signal
    available; blending both keeps ratings stable as the current season
    accumulates games rather than jumping the moment week 1 finishes."""
    seasons = (str(season - 2), str(season - 1), str(season))
    cur.execute(TRAINING_SQL, (seasons,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["home", "away", "home_score", "away_score"])
    model = NFLPowerRatings(alpha=5.0).fit(df)
    meta = {"alpha": 5.0, "n_games": len(df), "seasons": seasons}
    return model, meta


def _market_lines(season: int) -> dict[str, dict]:
    """Fresh pull, keyed by nflverse's own game_id -- market lines are
    only published closer to kickoff, so this window's lines are always
    read live rather than from whatever was stored at ingestion time."""
    df = nfl.import_schedules([season])
    lines = {}
    for _, row in df.iterrows():
        lines[row["game_id"]] = {
            "spread_line": row.get("spread_line"),
            "total_line": row.get("total_line"),
        }
    return lines


def build_candidates(model: NFLPowerRatings, home: str, away: str, home_id: int,
                     away_id: int, spread_line: float | None,
                     total_line: float | None) -> list[Inference]:
    pred = model.predict(home, away)
    context = {"predicted_margin": pred["predicted_margin"],
              "predicted_total": pred["predicted_total"],
              "sigma_margin": pred["sigma_margin"], "sigma_total": pred["sigma_total"]}
    candidates = []

    p_home_win = model.prob_home_wins(home, away)
    candidates.append(Inference("MONEYLINE", f"{home} win", None, "home", p_home_win,
                                home_id, context=context))
    candidates.append(Inference("MONEYLINE", f"{away} win", None, "away", 1 - p_home_win,
                                away_id, context=context))

    if spread_line is not None and not pd.isna(spread_line):
        # nflverse's spread_line is positive when the HOME team is
        # favored (verified empirically against 2025 results: margin
        # correlates positively with spread_line) -- the opposite sign
        # of this project's own SPREAD convention (grader.py: negative
        # line = that side favored), so home's own line is the negation.
        home_line = -float(spread_line)
        p_home_covers = model.prob_home_covers(home, away, home_line)
        candidates.append(Inference("SPREAD", f"{home} {home_line:+.1f}", home_line,
                                    "home", p_home_covers, home_id, context=context))
        candidates.append(Inference("SPREAD", f"{away} {-home_line:+.1f}", -home_line,
                                    "away", 1 - p_home_covers, away_id, context=context))

    if total_line is not None and not pd.isna(total_line):
        total_line = float(total_line)
        p_over = model.prob_over(home, away, total_line)
        candidates.append(Inference("TOTAL_POINTS", f"Over {total_line}", total_line,
                                    "over", p_over, context=context))
        candidates.append(Inference("TOTAL_POINTS", f"Under {total_line}", total_line,
                                    "under", 1 - p_over, context=context))

    return candidates


# position -> list of (market, column) -- a position can feed more than
# one market (e.g. a WR gets both receiving yards and receptions).
# Receptions applies to RB too (pass-catching backs are a real,
# separate prop market from rushing yards, not a rounding error on it).
STAT_COLUMN_BY_MARKET = {
    "QB": [("PLAYER_PASS_YARDS", "passing_yards")],
    "RB": [("PLAYER_RUSH_YARDS", "rushing_yards"), ("PLAYER_RECEPTIONS", "receptions")],
    "WR": [("PLAYER_RECEIVING_YARDS", "receiving_yards"), ("PLAYER_RECEPTIONS", "receptions")],
    "TE": [("PLAYER_RECEIVING_YARDS", "receiving_yards"), ("PLAYER_RECEPTIONS", "receptions")],
}
# Every position that can score a rushing or receiving TD -- includes
# QB deliberately: mobile QBs have a real, non-trivial rushing-TD rate
# (the rolling-rate model naturally produces near-zero probabilities
# for pocket passers on its own, no separate carve-out needed).
TD_ELIGIBLE_POSITIONS = ("QB", "RB", "WR", "TE")


def build_player_candidates(cur, depth_chart: dict, team_abbr: str,
                            kickoff: datetime) -> list[Inference]:
    candidates = []
    for position, market_columns in STAT_COLUMN_BY_MARKET.items():
        for nfl_player_id in depth_chart.get((team_abbr, position), []):
            cur.execute("SELECT player_id, full_name FROM futbol.players WHERE nfl_player_id = %s",
                       (nfl_player_id,))
            row = cur.fetchone()
            if not row:
                continue  # never appeared in an ingested box score -- no history to predict from
            player_id, player_name = row

            for market, column in market_columns:
                stats = rolling_yardage_stats(cur, player_id, column, kickoff)
                if stats is None:
                    continue
                context = {"avg_yards": stats["avg_yards"], "sigma": stats["sigma"],
                          "n_games": stats["n_games"]}
                for line in player_candidate_lines(stats["avg_yards"], stats["sigma"]):
                    p = player_prob_over(stats["avg_yards"], stats["sigma"], line)
                    if PROPS_OVER_BAND[0] <= p <= PROPS_OVER_BAND[1]:
                        candidates.append(Inference(market, f"{player_name} over {line}",
                                                    line, "over", p, subject_player_id=player_id,
                                                    context=context))
                    elif PROPS_UNDER_BAND[0] <= p <= PROPS_UNDER_BAND[1]:
                        candidates.append(Inference(market, f"{player_name} under {line}",
                                                    line, "under", 1 - p, subject_player_id=player_id,
                                                    context=context))

            if position in TD_ELIGIBLE_POSITIONS:
                td = rolling_td_rate(cur, player_id, kickoff)
                if td is not None:
                    p_td = player_prob_anytime_td(td["lambda"])
                    context = {"lambda": td["lambda"], "n_games": td["n_games"]}
                    # Same confidence-band philosophy as the yardage
                    # markets above, applied to P(yes) directly instead
                    # of P(over a line) -- "yes" when confidently likely,
                    # "no" when confidently unlikely, skip the ambiguous
                    # middle (and skip near-zero-probability players
                    # entirely, same as every other props market here).
                    if PROPS_OVER_BAND[0] <= p_td <= PROPS_OVER_BAND[1]:
                        candidates.append(Inference(
                            "PLAYER_ANYTIME_TD", f"{player_name} anytime TD", None, "yes",
                            p_td, subject_player_id=player_id, context=context))
                    elif PROPS_UNDER_BAND[0] <= p_td <= PROPS_UNDER_BAND[1]:
                        candidates.append(Inference(
                            "PLAYER_ANYTIME_TD", f"{player_name} no TD", None, "no",
                            1 - p_td, subject_player_id=player_id, context=context))
    return candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--days-ahead", type=int, default=14)
    args = ap.parse_args()
    from ops.pipeline_run import track_run, record_model_version_history

    with track_run(f"nfl_slate:{args.season}") as set_rows_written:
        conn = psycopg2.connect(DSN)
        written = 0
        with conn.cursor() as cur:
            model, meta = fit_model(cur, args.season)
            print(f"Fit on {meta['n_games']} games from seasons {meta['seasons']}")

            _mv_window = ",".join(meta["seasons"])
            _mv_params = json.dumps({"alpha": meta["alpha"]})
            _mv_metrics = json.dumps({"n_games": meta["n_games"],
                                       "sigma_margin": model.sigma_margin,
                                       "sigma_total": model.sigma_total})
            cur.execute(
                """INSERT INTO futbol.model_versions
                     (model_name, version_tag, training_window, params, train_metrics)
                   VALUES ('slate_generator_nfl', 'v1', %s, %s, %s)
                   ON CONFLICT (model_name, version_tag) DO UPDATE
                     SET training_window = EXCLUDED.training_window,
                         params = EXCLUDED.params, train_metrics = EXCLUDED.train_metrics
                   RETURNING model_version_id""",
                (_mv_window, _mv_params, _mv_metrics))
            model_version_id = cur.fetchone()[0]
            record_model_version_history(cur, "slate_generator_nfl", "v1",
                                          _mv_window, _mv_params, _mv_metrics)
            conn.commit()

            cur.execute(UPCOMING_SQL, (str(args.season), args.days_ahead))
            fixtures = cur.fetchall()
            print(f"{len(fixtures)} upcoming NFL fixture(s) without a slate "
                 f"(next {args.days_ahead} days)")

            lines_by_game_id = _market_lines(args.season)
            depth_chart = current_depth_chart(args.season)

            for (match_id, external_ref, home, away, home_id, away_id,
                home_abbr, away_abbr, kickoff) in fixtures:
                if not external_ref:
                    print(f"  SKIP {home} vs {away}: no external_ref")
                    continue
                game_id = external_ref.split(":", 1)[1]
                lines = lines_by_game_id.get(game_id, {})
                spread_line, total_line = lines.get("spread_line"), lines.get("total_line")
                has_market_line = not ((spread_line is None or pd.isna(spread_line)) and
                                       (total_line is None or pd.isna(total_line)))

                try:
                    candidates = (build_candidates(model, home, away, home_id, away_id,
                                                   spread_line, total_line)
                                 if has_market_line else [])
                    candidates += build_player_candidates(cur, depth_chart, home_abbr, kickoff)
                    candidates += build_player_candidates(cur, depth_chart, away_abbr, kickoff)
                    if not candidates:
                        print(f"  SKIP {home} vs {away}: no market line and no player "
                             f"prop candidates")
                        continue
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
