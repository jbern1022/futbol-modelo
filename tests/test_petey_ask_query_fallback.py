"""
Confirms Petey v2's free-text path degrades gracefully when Ollama
times out or errors -- part of the Petey evaluation harness (Todoist:
"Petey evaluation harness (golden prompt set)"). Mocked, not a real
20-second wait: requests.post is patched to raise the exact exception
class _ask_ollama_for_filter's docstring promises to handle
(requests.exceptions.Timeout), so this runs in milliseconds and stays
a real regression guard rather than a slow integration test.

Requires importing api.main, which opens a real DB connection pool at
module load time (ThreadedConnectionPool) -- skipped without a DSN to
connect with, same constraint as every other DB-backed test in this
suite. No Petey test before this one has imported api.main directly
for exactly this reason (see petey_filter.py/petey_translate.py's own
"no DB import at module load" design) -- this is deliberately narrow:
only _ask_ollama_for_filter, not the full /v1/ask/query endpoint
(which also needs a real Request object for rate limiting).
"""
import os
from unittest.mock import patch

import pytest
import requests

DSN = os.environ.get("FUTBOL_DSN")


@pytest.mark.skipif(not DSN, reason="FUTBOL_DSN not set -- api.main needs a DB pool to import")
class TestAskOllamaForFilterFallback:
    @pytest.fixture(autouse=True)
    def _db_env(self, monkeypatch):
        # api.main reads FUTBOL_RO_DSN specifically (not FUTBOL_DSN) --
        # using the same DSN read-only is fine here, this test never
        # writes, same pattern used to run the API locally this session.
        monkeypatch.setenv("FUTBOL_RO_DSN", DSN)

    def test_timeout_returns_none_not_an_exception(self):
        import api.main as main
        with patch("api.main.requests.post", side_effect=requests.exceptions.Timeout):
            result = main._ask_ollama_for_filter("How accurate are corners predictions in MLS?")
        assert result is None

    def test_connection_error_returns_none_not_an_exception(self):
        import api.main as main
        with patch("api.main.requests.post", side_effect=requests.exceptions.ConnectionError):
            result = main._ask_ollama_for_filter("How accurate are corners predictions in MLS?")
        assert result is None

    def test_non_json_response_returns_none(self):
        import api.main as main

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "not valid json at all"}

        with patch("api.main.requests.post", return_value=FakeResponse()):
            result = main._ask_ollama_for_filter("anything")
        assert result is None

    def test_json_array_instead_of_object_returns_none(self):
        # format=json only guarantees valid JSON syntax, not that it's
        # an object -- Ollama returning a bare list is valid JSON but
        # not a usable filter tree.
        import api.main as main

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "[1, 2, 3]"}

        with patch("api.main.requests.post", return_value=FakeResponse()):
            result = main._ask_ollama_for_filter("anything")
        assert result is None

    def test_real_success_case_still_works_through_the_mock_seam(self):
        # Regression guard on the mocking approach itself: confirms the
        # success path isn't accidentally broken by how these tests
        # patch requests.post.
        import api.main as main
        import json as jsonlib

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": jsonlib.dumps(
                    {"field": "market", "op": "=", "value": "CORNERS"})}

        with patch("api.main.requests.post", return_value=FakeResponse()):
            result = main._ask_ollama_for_filter("corners predictions?")
        assert result == {"field": "market", "op": "=", "value": "CORNERS"}
