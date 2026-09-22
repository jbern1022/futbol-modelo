import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from simulate_bankroll import STARTING_BANKROLL, FLAT_STAKE, simulate

DSN = os.environ.get("FUTBOL_DSN")


@pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")
class TestSimulateBankroll:
    """
    Real regression coverage for two bugs found building this: (1) the
    odds lookup must be bounded by kickoff, not the prediction's own
    locked_at -- locked_at can be weeks before odds ingestion ever
    starts for that match, so a locked_at-bounded query silently found
    zero bets against 96 real graded predictions that did have odds.
    (2) our own predictions.market ('PLAYER_GOALS') and the odds
    provider's market name ('PLAYER_ANYTIME_GOAL') genuinely differ and
    must be mapped, not assumed equal.
    """

    @pytest.fixture
    def conn(self):
        c = psycopg2.connect(DSN)
        yield c
        c.rollback()
        c.close()

    @pytest.fixture
    def match(self, conn):
        cur = conn.cursor()
        cur.execute("SELECT match_id, kickoff_utc FROM futbol.matches LIMIT 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no match row to attach a synthetic prediction to")
        return row

    def _make_prediction(self, cur, match_id, kickoff, market, side,
                         probability, locked_at, subject_player_id=None):
        cur.execute("SELECT model_version_id FROM futbol.model_versions LIMIT 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no model_versions row to attach a synthetic prediction to")
        model_version_id = row[0]
        cur.execute(
            """INSERT INTO futbol.predictions
                 (match_id, model_version_id, market, side, probability,
                  locked_at, statement, subject_player_id)
               VALUES (%s, %s, %s, %s, %s, %s, 'test prediction', %s)
               RETURNING prediction_id""",
            (match_id, model_version_id, market, side, probability,
             locked_at, subject_player_id))
        return cur.fetchone()[0]

    def _grade(self, cur, prediction_id, outcome):
        cur.execute(
            """INSERT INTO futbol.prediction_grades
                 (prediction_id, outcome, grader_version)
               VALUES (%s, %s, 'test')""",
            (prediction_id, outcome))

    def _add_odds(self, cur, match_id, market, selection, decimal_odds, fetched_at):
        cur.execute(
            """INSERT INTO futbol.match_odds_history
                 (match_id, bookmaker_id, bookmaker_name, market, selection,
                  decimal_odds, implied_probability, no_vig_probability, fetched_at)
               VALUES (%s, 1, 'Test Bookmaker', %s, %s, %s, %s, %s, %s)""",
            (match_id, market, selection, decimal_odds,
             1 / decimal_odds, 1 / decimal_odds, fetched_at))

    def test_hit_profits_at_the_earliest_snapshot_price(self, conn, match):
        match_id, kickoff = match
        cur = conn.cursor()
        # locked_at deliberately weeks before kickoff -- odds land much
        # later, only bounded by kickoff.
        locked_at = kickoff - timedelta(days=30)
        pred_id = self._make_prediction(cur, match_id, kickoff, "1X2", "home", 0.6, locked_at)
        self._grade(cur, pred_id, "hit")
        # Earlier (opening) snapshot at worse odds than a later one --
        # the earliest one must win, not the best overall.
        self._add_odds(cur, match_id, "1X2", "Home", 2.0, kickoff - timedelta(days=2))
        self._add_odds(cur, match_id, "1X2", "Home", 3.0, kickoff - timedelta(hours=1))

        rows = simulate(cur, "1X2", "1X2")
        row = next(r for r in rows if r["prediction_id"] == pred_id)
        assert row["decimal_odds"] == 2.0
        assert row["profit"] == FLAT_STAKE * (2.0 - 1)
        assert row["bankroll_after"] == STARTING_BANKROLL + row["profit"]

    def test_miss_loses_exactly_the_stake(self, conn, match):
        match_id, kickoff = match
        cur = conn.cursor()
        locked_at = kickoff - timedelta(days=10)
        pred_id = self._make_prediction(cur, match_id, kickoff, "1X2", "away", 0.3, locked_at)
        self._grade(cur, pred_id, "miss")
        self._add_odds(cur, match_id, "1X2", "Away", 4.5, kickoff - timedelta(hours=3))

        rows = simulate(cur, "1X2", "1X2")
        row = next(r for r in rows if r["prediction_id"] == pred_id)
        assert row["profit"] == -FLAT_STAKE

    def test_no_odds_before_kickoff_is_skipped_not_fabricated(self, conn, match):
        match_id, kickoff = match
        cur = conn.cursor()
        locked_at = kickoff - timedelta(days=10)
        pred_id = self._make_prediction(cur, match_id, kickoff, "1X2", "draw", 0.25, locked_at)
        self._grade(cur, pred_id, "hit")
        # Only a post-kickoff snapshot exists -- must not be used.
        self._add_odds(cur, match_id, "1X2", "Draw", 3.5, kickoff + timedelta(hours=2))

        rows = simulate(cur, "1X2", "1X2")
        assert all(r["prediction_id"] != pred_id for r in rows)

    def test_player_goals_market_maps_to_the_odds_providers_market_name(self, conn, match):
        match_id, kickoff = match
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO futbol.players (full_name) VALUES ('Test Scorer') RETURNING player_id")
        player_id = cur.fetchone()[0]
        locked_at = kickoff - timedelta(days=5)
        pred_id = self._make_prediction(
            cur, match_id, kickoff, "PLAYER_GOALS", "over", 0.3, locked_at,
            subject_player_id=player_id)
        self._grade(cur, pred_id, "hit")
        # Stored under the ODDS provider's market name, not ours --
        # this is exactly the mismatch this test guards against.
        cur.execute(
            """INSERT INTO futbol.match_odds_history
                 (match_id, bookmaker_id, bookmaker_name, market, selection,
                  player_id, decimal_odds, implied_probability, no_vig_probability, fetched_at)
               VALUES (%s, 1, 'Test Bookmaker', 'PLAYER_ANYTIME_GOAL', 'Test Scorer',
                       %s, 2.62, 0.38, NULL, %s)""",
            (match_id, player_id, kickoff - timedelta(hours=6)))

        rows = simulate(cur, "PLAYER_GOALS", "PLAYER_ANYTIME_GOAL")
        row = next(r for r in rows if r["prediction_id"] == pred_id)
        assert row["decimal_odds"] == 2.62
