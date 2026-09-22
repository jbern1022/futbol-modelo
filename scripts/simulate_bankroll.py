"""
Paper-trading / bankroll simulation -- a real ROI curve denominated in
money, not percentages (Todoist: "futbol-modelo: paper-trading /
bankroll simulation", Phase 3).

    python scripts/simulate_bankroll.py

Flat-stake v1: every graded prediction with a real bookmaker odds
snapshot available before kickoff gets a fixed stake, priced at the
EARLIEST such snapshot (effectively the opening line) rather than the
closing line -- closing is the price after the market has already
moved, not what a real bettor would have locked in.

This is NOT the same timestamp as the prediction's own locked_at.
predictions.locked_at can be weeks before kickoff (auto_slate.py slates
matches up to 45 days out), while odds ingestion only starts fetching a
match once it's within days_ahead of kickoff (7 days daily, 1 day
intraday -- see fetch_and_store_odds) -- confirmed live: every one of
this match's odds snapshots was fetched over a month after its
prediction was locked. The model's own belief was already fixed at
locked_at regardless; what matters for "could this bet actually have
been placed" is whether real market odds existed by kickoff, not
whether they existed by locked_at. Predictions with no odds snapshot
at all before kickoff are skipped entirely, not backfilled with a
fabricated price.

Full recompute every run (truncate + insert), matching this project's
"no saved checkpoints, retrain from scratch" pattern everywhere else --
see bankroll_simulation's own comment in sql/schema.sql.

Currently 1X2 only in practice: BTTS/PLAYER_ANYTIME_GOAL odds ingestion
just shipped (2026-09-21) and has no accumulated history yet, but this
script is market-generic and will pick them up automatically once
match_odds_history has rows for them.
"""
import os
import sys
from datetime import timezone
from typing import Any

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ops.pipeline_run import track_run

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

STARTING_BANKROLL = 1000.0
FLAT_STAKE = 10.0

# Our own predictions.market name -> the odds provider's market name
# in match_odds_history (see src/ingestion/api_football.py's
# ODDS_BET_IDS). These genuinely differ for the player market: our
# slate generator calls it PLAYER_GOALS (scripts/generate_slate.py's
# build_player_goal_inference), while the odds come tagged
# PLAYER_ANYTIME_GOAL (the bookmaker's own bet-type name) -- same
# real-world bet, different string, would never have joined without
# this map.
BETTABLE_MARKETS: dict[str, str] = {
    "1X2": "1X2",
    "BTTS": "BTTS",
    "PLAYER_GOALS": "PLAYER_ANYTIME_GOAL",
}


def simulate(cur, prediction_market: str, odds_market: str) -> list[dict[str, Any]]:
    """One market's flat-stake bankroll curve, in kickoff order.
    Bankroll doesn't compound across markets -- markets are
    conceptually separate portfolios here (a flat stake doesn't need
    shared state to run correctly one at a time; a real Kelly-staked
    version would)."""
    is_player_market = prediction_market == "PLAYER_GOALS"

    cur.execute(
        """SELECT p.prediction_id, p.match_id, p.side, p.subject_player_id,
                  p.probability, p.locked_at, m.kickoff_utc, g.outcome
           FROM futbol.predictions p
           JOIN futbol.prediction_grades g ON g.prediction_id = p.prediction_id
           JOIN futbol.matches m ON m.match_id = p.match_id
           WHERE p.market = %s AND p.locked_at IS NOT NULL
             AND g.outcome IN ('hit', 'miss')
           ORDER BY m.kickoff_utc ASC""",
        (prediction_market,))
    predictions = cur.fetchall()

    bankroll = STARTING_BANKROLL
    rows = []
    for pred_id, match_id, side, subject_player_id, prob, locked_at, kickoff, outcome in predictions:
        # Earliest real snapshot before kickoff (the opening line, not
        # closing) -- see this function's docstring for why this is
        # kickoff-bounded rather than locked_at-bounded. Bookmakers get
        # fetched in a single run's loop, seconds apart, not identical
        # microsecond timestamps -- so "the same moment" means within
        # 10 minutes of the actual earliest snapshot, not an exact
        # match. Among rows in that window, take the best available
        # price, matching a bettor who shops across books.
        subject_filter = "moh.player_id = %s" if is_player_market else "lower(moh.selection) = %s"
        subject_value = subject_player_id if is_player_market else side
        cur.execute(
            f"""WITH earliest AS (
                    SELECT min(fetched_at) AS ts FROM futbol.match_odds_history moh
                    WHERE moh.match_id = %s AND moh.market = %s
                      AND {subject_filter} AND moh.fetched_at <= %s
                )
                SELECT moh.decimal_odds FROM futbol.match_odds_history moh, earliest
                WHERE moh.match_id = %s AND moh.market = %s
                  AND {subject_filter} AND moh.fetched_at <= earliest.ts + interval '10 minutes'
                ORDER BY moh.decimal_odds DESC
                LIMIT 1""",
            (match_id, odds_market, subject_value, kickoff,
             match_id, odds_market, subject_value))
        odds_row = cur.fetchone()
        if odds_row is None:
            continue
        decimal_odds = float(odds_row[0])

        stake = FLAT_STAKE
        if outcome == "hit":
            profit = stake * (decimal_odds - 1)
        else:
            profit = -stake
        bankroll += profit

        rows.append({
            "prediction_id": pred_id, "match_id": match_id, "kickoff_utc": kickoff,
            "market": prediction_market, "side": side, "model_probability": float(prob),
            "decimal_odds": decimal_odds, "stake": stake, "outcome": outcome,
            "profit": profit, "bankroll_after": bankroll,
        })
    return rows


def main():
    conn = psycopg2.connect(DSN)
    with track_run("simulate_bankroll") as set_rows_written:
        all_rows: list[dict[str, Any]] = []
        with conn.cursor() as cur:
            for prediction_market, odds_market in BETTABLE_MARKETS.items():
                rows = simulate(cur, prediction_market, odds_market)
                print(f"[{prediction_market}] {len(rows)} bet(s) with a real odds snapshot available")
                all_rows.extend(rows)

        with conn.cursor() as cur:
            cur.execute("TRUNCATE futbol.bankroll_simulation")
            for r in all_rows:
                cur.execute(
                    """INSERT INTO futbol.bankroll_simulation
                         (prediction_id, match_id, kickoff_utc, market, side,
                          model_probability, decimal_odds, stake, outcome,
                          profit, bankroll_after)
                       VALUES (%(prediction_id)s, %(match_id)s, %(kickoff_utc)s,
                               %(market)s, %(side)s, %(model_probability)s,
                               %(decimal_odds)s, %(stake)s, %(outcome)s,
                               %(profit)s, %(bankroll_after)s)""",
                    r)
        conn.commit()
        set_rows_written(len(all_rows))
        print(f"done: {len(all_rows)} bet(s) written, "
              f"final bankroll per market printed above is in the table")
    conn.close()


if __name__ == "__main__":
    main()
