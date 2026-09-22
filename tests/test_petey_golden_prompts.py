"""
Petey v2 golden-prompt harness: real free-text questions against the
LIVE Ollama instance (192.168.4.48:11434, llama3.2:latest), asserting
the translated filter both (a) passes petey_filter's real validator
and (b) contains the fields/values the question actually asked for.
Completes the Petey evaluation harness (Todoist: "Petey evaluation
harness (golden prompt set)") -- the "no judgment-word leakage" slice
shipped 2026-09-03; this is the "correct filter JSON" slice that was
blocked until Petey v2 existed (it does now, confirmed 2026-09-21).

DESIGN NOTE, learned the hard way running this live: an earlier draft
of this file had one pytest case per prompt, expecting each to
deterministically pass. Real testing exposed how wrong that
assumption was -- three separate live runs against the identical 20
prompts scored 19/20, then 18/20 with a different failure, then
13/20 with FIVE new failures sharing one root cause never seen before
(Ollama hallucinating the literal string "None" as a field's value for
fields the question never mentioned -- a real, repeated violation of
this prompt's own "under-including is safer than guessing" rule,
happening on different questions each run). format=json only
constrains output to be syntactically valid JSON; it does not make a
3B-param model's actual word choices deterministic.

Per-prompt hard pass/fail is the wrong shape for that. This harness
instead runs the whole set once and reports an aggregate pass rate,
matching how real LLM eval harnesses work -- printed for a human to
read as a trend over time, with only a loose regression floor as a
hard assertion (catches "the model swap broke everything", not "one
specific phrasing had a bad sampling draw this run"). The validator's
SAFETY property already held on every single one of these failures --
nothing unsafe was ever returned, "None" was correctly rejected every
time. What this measures is Ollama's translation ACCURACY, which is
allowed to be imperfect and still ship, given the validator is the
actual safety boundary (see docs/petey-spec.md's core design
principle).

Skipped entirely if Ollama isn't reachable -- this hits a real
GPU-backed service on the home network, not something CI or a laptop
off that network can assume is there.
"""
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from petey_filter import FilterCondition, FilterGroup, FilterValidationError, validate_filter

DSN = os.environ.get("FUTBOL_DSN")
OLLAMA_URL = os.environ.get("FUTBOL_OLLAMA_URL", "http://192.168.4.48:11434")

# Below this, something is badly wrong (a broken prompt, a much worse
# model swap) rather than ordinary sampling variance -- observed real
# scores across three live runs were 19/20, 18/20, 13/20 (65-95%), so
# this floor sits meaningfully below the worst real run seen, not at
# some aspirational number.
MIN_PASS_RATE = 0.5


def _ollama_reachable() -> bool:
    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not DSN or not _ollama_reachable(),
    reason="FUTBOL_DSN not set, or Ollama unreachable at FUTBOL_OLLAMA_URL")


def _flatten(node) -> set[tuple[str, str, str]]:
    """All (field, op, value) leaves in a validated filter tree,
    regardless of and/or nesting -- structure-independent comparison."""
    if isinstance(node, FilterCondition):
        return {(node.field, node.op, node.value)}
    if isinstance(node, FilterGroup):
        out: set[tuple[str, str, str]] = set()
        for child in node.children:
            out |= _flatten(child)
        return out
    raise TypeError(f"unexpected node type: {type(node)!r}")


def _ask(question: str) -> tuple[dict | None, float]:
    """Real call to _ask_ollama_for_filter (api.main), timed. Requires
    FUTBOL_RO_DSN to import api.main (opens a real DB pool at module
    load) -- set from FUTBOL_DSN read-only, same as every other
    DB-backed test that borrows it this way this session."""
    os.environ.setdefault("FUTBOL_RO_DSN", DSN)
    import api.main as main
    start = time.monotonic()
    raw = main._ask_ollama_for_filter(question)
    elapsed = time.monotonic() - start
    return raw, elapsed


# (question, required (field, value) pairs that MUST appear in the
# validated filter for a pass) -- op is deliberately unchecked, "="
# is the only op these natural-language questions would realistically
# produce, and pinning it too would make this brittle over something
# not actually being tested here.
GOLDEN_PROMPTS: list[tuple[str, set[tuple[str, str]]]] = [
    ("How accurate are corners predictions in MLS?", {("market", "CORNERS"), ("league", "MLS")}),
    ("Show me predictions that missed in the EPL", {("league", "EPL"), ("outcome", "miss")}),
    ("What's your record on Juventus matches?", {("team", "Juventus")}),
    ("How well do you predict shots on target in Serie A?", {("market", "SOT"), ("league", "SERIE_A")}),
    ("What's your hit rate on BTTS predictions?", {("market", "BTTS")}),
    ("How accurate is the model for La Liga?", {("league", "LA_LIGA")}),
    ("Show me hits for total goals predictions", {("market", "TOTAL_GOALS"), ("outcome", "hit")}),
    ("What's your track record predicting player goals?", {("market", "PLAYER_GOALS")}),
    ("How accurate are your predictions on the home side?", {("side", "home")}),
    ("What's your accuracy on away-side predictions?", {("side", "away")}),
    ("Show me your misses for 1X2 in MLS", {("market", "1X2"), ("league", "MLS"), ("outcome", "miss")}),
    ("How good are corners predictions overall?", {("market", "CORNERS")}),
    ("What's your record on Real Madrid?", {("team", "Real Madrid")}),
    ("How accurate are goalkeeper saves predictions?", {("market", "PLAYER_SAVES")}),
    ("Show me EPL hits", {("league", "EPL"), ("outcome", "hit")}),
    ("What's the moneyline accuracy in the NFL?", {("market", "MONEYLINE"), ("league", "NFL")}),
    ("How accurate are spread predictions?", {("market", "SPREAD")}),
    ("What's your record on the World Cup?", {("league", "WC")}),
    ("Show me total points predictions in the NBA", {("market", "TOTAL_POINTS"), ("league", "NBA")}),
    ("How accurate were your predictions on Inter?", {("team", "Inter")}),
]


def test_golden_prompt_set_pass_rate_and_latency():
    results = []  # (question, passed, detail, elapsed)
    for question, required in GOLDEN_PROMPTS:
        raw, elapsed = _ask(question)
        if raw is None:
            results.append((question, False, "Ollama returned no usable JSON (fallback fired)", elapsed))
            continue
        try:
            validated = validate_filter(raw)
        except FilterValidationError as e:
            results.append((question, False, f"failed validation: {e} -- raw: {raw}", elapsed))
            continue
        found = {(f, v) for f, _op, v in _flatten(validated)}
        missing = required - found
        if missing:
            results.append((question, False, f"missing {missing} -- got {found} from raw {raw}", elapsed))
        else:
            results.append((question, True, "ok", elapsed))

    passed = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    pass_rate = len(passed) / len(results)

    times = [r[3] for r in results if r[1]]  # latency only over successful calls
    times.sort()
    p50 = times[len(times) // 2] if times else 0.0
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))] if times else 0.0

    print(f"\nPetey golden-prompt set: {len(passed)}/{len(results)} passed "
          f"({pass_rate:.0%}), latency p50={p50:.2f}s p95={p95:.2f}s "
          f"max={max(times) if times else 0:.2f}s")
    for question, _passed, detail, elapsed in failed:
        print(f"  FAIL [{elapsed:.2f}s] {question!r}: {detail}")

    assert pass_rate >= MIN_PASS_RATE, (
        f"pass rate {pass_rate:.0%} ({len(passed)}/{len(results)}) is below the "
        f"{MIN_PASS_RATE:.0%} regression floor -- see printed failures above")
    if times:
        assert max(times) < 20.0, (
            f"a call took {max(times):.2f}s -- should be well under the 20s Ollama timeout")
