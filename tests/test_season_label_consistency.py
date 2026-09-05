"""
Regression test for the season-label mismatch found while scoping the
idempotency test (see Todoist): api_football.py's backfill_primary()
used a bare-year label ("2026") unconditionally, while loader.py's
_season_label() (used for the same leagues via Understat/FBref) has
used hyphenated "YYYY-YY" labels for every prior EPL/SERIE_A/LA_LIGA
season in the DB. Since upsert_season's dedup key includes the label,
a mismatched format doesn't error -- it silently creates a second
season row and duplicates every fixture under it.
"""
from ingestion.api_football import season_label_for


def test_cross_year_leagues_get_hyphenated_labels():
    assert season_label_for("EPL", 2026) == "2026-27"
    assert season_label_for("SERIE_A", 2026) == "2026-27"
    assert season_label_for("LA_LIGA", 2026) == "2026-27"


def test_single_year_league_gets_bare_year():
    assert season_label_for("MLS", 2026) == "2026"


def test_matches_loader_pys_established_convention():
    """loader.py's _season_label("2627") -> "2026-27" for the same real
    season -- this is the exact string that has to match for the two
    ingestion paths to reuse the same season row instead of duplicating."""
    from ingestion.loader import _season_label
    assert season_label_for("EPL", 2026) == _season_label("2627")
    assert season_label_for("SERIE_A", 2025) == _season_label("2526")
