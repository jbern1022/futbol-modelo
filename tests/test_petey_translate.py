"""
Tests for the Petey v2 free-text -> JSON filter prompt builder
(api/petey_translate.py). Pure string-building, no Ollama/DB needed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from petey_filter import ALLOWED_MARKET_VALUES
from petey_translate import build_prompt


def test_embeds_the_question_verbatim():
    prompt = build_prompt("How accurate are corners predictions in MLS?")
    assert "How accurate are corners predictions in MLS?" in prompt


def test_lists_every_allowed_market_value():
    prompt = build_prompt("anything")
    for market in ALLOWED_MARKET_VALUES:
        assert market in prompt


def test_includes_the_under_inclusion_rule():
    # the specific instruction that fixed the real over-inclusion bug
    # found through live testing -- regression-guard against it being
    # accidentally dropped in a future edit.
    prompt = build_prompt("anything")
    assert "Under-including is always safer than guessing" in prompt


def test_question_with_braces_does_not_break_formatting():
    # build_prompt uses str.format() with literal {{ }} in the template
    # -- a question containing a brace character must not collide with
    # that or raise/corrupt the prompt.
    prompt = build_prompt("What about {CORNERS} predictions?")
    assert "What about {CORNERS} predictions?" in prompt
