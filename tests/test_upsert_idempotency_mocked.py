"""
Mock-based idempotency tests for loader.py's upsert_team and upsert_season.

The live-DB idempotency test (test_ingestion_idempotency.py) is opt-in only
because it makes real external network calls. These tests run offline and fast,
covering the cache-path and DB-path independently.
"""
from unittest.mock import MagicMock, call

import pytest

import ingestion.loader as loader


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset module-level caches between tests so they don't bleed."""
    loader._team_id_cache.clear()
    loader._season_id_cache.clear()
    yield
    loader._team_id_cache.clear()
    loader._season_id_cache.clear()


def _make_cur(returning_id: int) -> MagicMock:
    cur = MagicMock()
    cur.fetchone.return_value = (returning_id,)
    return cur


# ---------- upsert_team ----------

def test_upsert_team_queries_db_on_first_call():
    cur = _make_cur(42)
    result = loader.upsert_team(cur, "Arsenal")
    assert result == 42
    cur.execute.assert_called_once()


def test_upsert_team_returns_cached_id_on_second_call():
    cur = _make_cur(42)
    loader.upsert_team(cur, "Arsenal")
    # Reset call count — second call must NOT hit DB
    cur.reset_mock()
    result = loader.upsert_team(cur, "Arsenal")
    assert result == 42
    cur.execute.assert_not_called()


def test_upsert_team_different_teams_each_query_db():
    cur = _make_cur(1)
    loader.upsert_team(cur, "Arsenal")
    cur.fetchone.return_value = (2,)
    result = loader.upsert_team(cur, "Chelsea")
    assert result == 2
    assert cur.execute.call_count == 2


# ---------- upsert_season ----------

def test_upsert_season_queries_db_on_first_call():
    cur = _make_cur(7)
    result = loader.upsert_season(cur, league_id=1, label="2025-26")
    assert result == 7
    cur.execute.assert_called_once()


def test_upsert_season_returns_cached_id_on_second_call():
    cur = _make_cur(7)
    loader.upsert_season(cur, league_id=1, label="2025-26")
    cur.reset_mock()
    result = loader.upsert_season(cur, league_id=1, label="2025-26")
    assert result == 7
    cur.execute.assert_not_called()


def test_upsert_season_different_league_different_cache_key():
    cur = _make_cur(7)
    loader.upsert_season(cur, league_id=1, label="2025-26")
    cur.fetchone.return_value = (9,)
    result = loader.upsert_season(cur, league_id=2, label="2025-26")
    assert result == 9
    assert cur.execute.call_count == 2
