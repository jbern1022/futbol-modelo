"""
Petey v2's free-text -> JSON filter prompt (docs/petey-spec.md, ADR-003).

Pure string-building, no DB/Ollama import at module load -- same
unit-testable-without-a-live-service shape as judgment_filter.py and
petey_filter.py. The actual Ollama call lives in api/main.py alongside
_ask_ollama, since it needs the same instrumentation.

The allowed-values lists are built FROM petey_filter's own allowlists
rather than duplicated as separate string literals -- the prompt and
the validator drifting out of sync would be worse than either being
individually correct, since a stale prompt would just train Ollama to
propose values the validator now rejects.

Live-tested against real Ollama output (llama3.2:latest, format=json)
before landing on this shape -- see api/petey_filter.py's changelog
comment and its test suite for the concrete bugs an earlier draft of
this prompt produced (market/side field confusion, invented "weather"
market, nonsense season values). The three-example few-shot plus the
explicit "only include what's actually specified" rule is what fixed
the over-inclusion pattern; the per-field value allowlist in the
validator is what catches everything the prompt still gets wrong.
"""
from __future__ import annotations

from petey_filter import (
    ALLOWED_FIELDS,
    ALLOWED_LEAGUE_VALUES,
    ALLOWED_MARKET_VALUES,
    ALLOWED_OPERATORS,
    ALLOWED_OUTCOME_VALUES,
    ALLOWED_SIDE_VALUES,
)

_PROMPT_TEMPLATE = """You translate a sports-analytics question into a JSON filter tree. Output ONLY the JSON object, nothing else -- no explanation, no markdown fences.

Allowed fields: {fields}
Allowed operators: {operators}
Combine multiple conditions with {{"and": [...]}} or {{"or": [...]}}. A single condition can be a bare leaf, no wrapper needed.

CRITICAL RULE: only include a condition for a field the question actually specifies or clearly implies. Never add a field just because an example showed it -- if the question doesn't mention a market, do not include a "market" condition at all. Under-including is always safer than guessing.

Allowed market values: {markets}
Allowed league values: {leagues}
Allowed outcome values: {outcomes}
Allowed side values: {sides}
season values look like "2025" or "2025-26" -- if the question says "this season" or "this year" and you don't know the actual current season, omit the season condition entirely rather than guessing.

Example 1:
Question: How accurate are corners predictions in MLS?
JSON: {{"and": [{{"field": "market", "op": "=", "value": "CORNERS"}}, {{"field": "league", "op": "=", "value": "MLS"}}]}}

Example 2:
Question: Show me predictions that missed in the EPL
JSON: {{"and": [{{"field": "league", "op": "=", "value": "EPL"}}, {{"field": "outcome", "op": "=", "value": "miss"}}]}}

Example 3:
Question: What's your record on Juventus matches?
JSON: {{"field": "team", "op": "=", "value": "Juventus"}}

Now translate this question:
Question: {question}
JSON:"""


def build_prompt(question: str) -> str:
    return _PROMPT_TEMPLATE.format(
        fields=", ".join(sorted(ALLOWED_FIELDS)),
        operators=", ".join(sorted(ALLOWED_OPERATORS)),
        markets=", ".join(sorted(ALLOWED_MARKET_VALUES)),
        leagues=", ".join(sorted(ALLOWED_LEAGUE_VALUES)),
        outcomes=", ".join(sorted(ALLOWED_OUTCOME_VALUES)),
        sides=", ".join(sorted(ALLOWED_SIDE_VALUES)),
        question=question,
    )
