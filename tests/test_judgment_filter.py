"""
Regression test for Petey's judgment-word filter (api/judgment_filter.py).
Pure logic, no database needed -- always runs, unlike most of this
project's tests.

Found and fixed a real bug while building this: the original filter
used plain substring matching (`word in text`), which false-positives
on "low" inside "allowed" or "yellow" -- "Yellow Cards" is a real
TEAM_STATS option in the Petey widget, so every yellow-cards answer
was silently forced into the deterministic fallback instead of
Ollama's real phrasing, with no visible sign anything was wrong.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from judgment_filter import contains_unsupported_judgment


def test_flags_standalone_judgment_words():
    assert contains_unsupported_judgment("The team has struggled recently.")
    assert contains_unsupported_judgment("That is a good result.")
    assert contains_unsupported_judgment("Confidence is high for this pick.")


def test_case_insensitive():
    assert contains_unsupported_judgment("STRUGGLED badly")
    assert contains_unsupported_judgment("Good result")


def test_does_not_flag_allowed():
    assert not contains_unsupported_judgment("The team allowed 2 goals this match.")


def test_does_not_flag_yellow_cards():
    assert not contains_unsupported_judgment("They averaged 1.4 yellow cards per game.")


def test_does_not_flag_other_low_substring_words():
    for sentence in [
        "The score stayed below expectations.",
        "The pace was slow in the second half.",
        "The tempo began to flow midway through.",
    ]:
        assert not contains_unsupported_judgment(sentence), sentence


def test_clean_neutral_sentence_is_not_flagged():
    assert not contains_unsupported_judgment(
        "n=14, 57.1% hit rate over the last 10 games.")
