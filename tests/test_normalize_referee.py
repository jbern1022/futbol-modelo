"""
Regression test for _normalize_referee (src/ingestion/api_football.py) --
API-Football's referee field format is inconsistent across leagues,
confirmed on a real 15-fixture sample: EPL gives a bare name, La Liga/
Serie A sometimes append ", Country".
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ingestion.api_football import _normalize_referee


def test_bare_name_unchanged():
    assert _normalize_referee("Peter Bankes") == "Peter Bankes"


def test_strips_trailing_country():
    assert _normalize_referee("Ricardo De Burgos Bengoetxea, Spain") == "Ricardo De Burgos Bengoetxea"


def test_strips_trailing_country_short_name():
    assert _normalize_referee("Juan Martínez, Spain") == "Juan Martínez"


def test_none_input_returns_none():
    assert _normalize_referee(None) is None


def test_empty_string_returns_none():
    assert _normalize_referee("") is None


def test_whitespace_only_returns_none():
    assert _normalize_referee("   ") is None
