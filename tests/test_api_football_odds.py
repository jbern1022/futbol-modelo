import os

import psycopg2
import pytest

from ingestion.api_football import (_api_football_fixture_id, normalize_match_winner_odds,
                                    remove_overround)

DSN = os.environ.get("FUTBOL_DSN")


def test_normalize_match_winner_odds_flattens_bookmakers():
    response = [{
        "fixture": {"id": 123},
        "bookmakers": [{
            "id": 6,
            "name": "Example Bookmaker",
            "bets": [{
                "id": 1,
                "name": "Match Winner",
                "values": [
                    {"value": "Home", "odd": "2.10"},
                    {"value": "Draw", "odd": "3.40"},
                    {"value": "Away", "odd": "3.25"},
                ],
            }],
        }],
    }]

    assert normalize_match_winner_odds(response) == [
        {
            "fixture_id": 123,
            "bookmaker_id": 6,
            "bookmaker_name": "Example Bookmaker",
            "market": "1X2",
            "selection": "Home",
            "decimal_odds": 2.10,
        },
        {
            "fixture_id": 123,
            "bookmaker_id": 6,
            "bookmaker_name": "Example Bookmaker",
            "market": "1X2",
            "selection": "Draw",
            "decimal_odds": 3.40,
        },
        {
            "fixture_id": 123,
            "bookmaker_id": 6,
            "bookmaker_name": "Example Bookmaker",
            "market": "1X2",
            "selection": "Away",
            "decimal_odds": 3.25,
        },
    ]


def test_normalize_match_winner_odds_skips_invalid_values_and_other_markets():
    response = [{
        "fixture": {"id": 123},
        "bookmakers": [{
            "bets": [
                {"id": 2, "values": [{"value": "Over 2.5", "odd": "1.80"}]},
                {"id": 1, "values": [
                    {"value": "Home", "odd": "1.00"},
                    {"value": "Away", "odd": "not-a-number"},
                ]},
            ],
        }],
    }]

    assert normalize_match_winner_odds(response) == []


def test_remove_overround_normalizes_market_probabilities():
    records = [
        {"selection": "Home", "decimal_odds": 2.0},
        {"selection": "Draw", "decimal_odds": 4.0},
        {"selection": "Away", "decimal_odds": 4.0},
    ]

    result = remove_overround(records)

    assert result[0]["implied_probability"] == 0.5
    assert result[0]["no_vig_probability"] == 0.5
    assert sum(record["no_vig_probability"] for record in result) == 1.0


def test_api_football_fixture_id_parses_the_real_format():
    assert _api_football_fixture_id("api-football:123456") == 123456


def test_api_football_fixture_id_returns_none_for_other_sources():
    # EPL/SERIE_A/LA_LIGA matches come from Understat/FBref via
    # loader.py and never get this format -- odds can't be looked up
    # for them yet (see the function's own docstring for why).
    assert _api_football_fixture_id(None) is None
    assert _api_football_fixture_id("") is None
    assert _api_football_fixture_id("understat:987") is None
    assert _api_football_fixture_id("api-football:not-a-number") is None


@pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- no live DB to check against")
class TestMatchOddsUpsert:
    """
    Verifies the match_odds table's actual constraint design (requires
    migration 0010 applied) -- not fetch_and_store_odds() itself, which
    makes a real external API call and has no automated test, matching
    this module's existing backfill()/backfill_primary() (also
    untested for the same reason).
    """

    @pytest.fixture
    def conn(self):
        c = psycopg2.connect(DSN)
        yield c
        c.rollback()
        c.close()

    def _any_match_id(self, cur):
        cur.execute("SELECT match_id FROM futbol.matches LIMIT 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no match row to attach the test odds to")
        return row[0]

    def test_reinserting_the_same_selection_updates_in_place(self, conn):
        cur = conn.cursor()
        match_id = self._any_match_id(cur)

        cur.execute(
            """INSERT INTO futbol.match_odds
                   (match_id, bookmaker_id, bookmaker_name, market, selection,
                    decimal_odds, implied_probability, no_vig_probability)
               VALUES (%s, 999, 'Test Bookmaker', '1X2', 'Home', 2.0, 0.5, 0.5)
               ON CONFLICT (match_id, bookmaker_id, market, selection)
               DO UPDATE SET decimal_odds = EXCLUDED.decimal_odds,
                             implied_probability = EXCLUDED.implied_probability,
                             no_vig_probability = EXCLUDED.no_vig_probability,
                             fetched_at = now()""",
            (match_id,))
        # Re-fetch with different odds for the same selection -- should
        # update the existing row, not create a second one.
        cur.execute(
            """INSERT INTO futbol.match_odds
                   (match_id, bookmaker_id, bookmaker_name, market, selection,
                    decimal_odds, implied_probability, no_vig_probability)
               VALUES (%s, 999, 'Test Bookmaker', '1X2', 'Home', 2.5, 0.4, 0.4)
               ON CONFLICT (match_id, bookmaker_id, market, selection)
               DO UPDATE SET decimal_odds = EXCLUDED.decimal_odds,
                             implied_probability = EXCLUDED.implied_probability,
                             no_vig_probability = EXCLUDED.no_vig_probability,
                             fetched_at = now()""",
            (match_id,))

        cur.execute(
            """SELECT COUNT(*), MAX(decimal_odds) FROM futbol.match_odds
               WHERE match_id = %s AND bookmaker_id = 999 AND selection = 'Home'""",
            (match_id,))
        count, latest_odds = cur.fetchone()
        assert count == 1
        assert float(latest_odds) == 2.5