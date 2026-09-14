"""
Petey v2's JSON filter validator + compiler (docs/petey-spec.md, ADR-003).

"Ollama never writes SQL, and never sees the schema... If Ollama proposes
a field or operator not on the allowlist, the request is rejected
outright before it gets anywhere near the database. Safety comes from
the validator, not from trusting the model to behave." This module is
that validator, plus the deterministic compiler that turns a validated
filter into a parameterized WHERE clause against v_petey_predictions
(migration 0017) -- the one fixed base query this is ever allowed to
extend.

Split out from api/main.py the same way judgment_filter.py is: pure,
unit-testable, no DB import at module load time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Real season labels are either a bare year (MLS: "2025") or a
# hyphenated split-year (EPL/SERIE_A/LA_LIGA: "2025-26") -- found
# necessary the same way as the other value checks: live-tested
# questions like "this season" / "this year" produced values like
# "this season", "1", and ">= '0'" for the season field, none of which
# would ever match a real row, silently returning wrong (usually empty)
# results instead of a clear rejection.
_SEASON = re.compile(r"^\d{4}(-\d{2})?$")

ALLOWED_FIELDS = {"market", "league", "team", "season", "side", "outcome", "kickoff_date"}
ALLOWED_OPERATORS = {"=", ">", "<", ">=", "<="}
ALLOWED_BOOL_OPS = {"and", "or"}

# Per-field value allowlists for the fields with a fixed, known domain --
# found necessary through live testing against real Ollama output, not
# hypothetically: a first-draft prompt put "SOT" (a market code) in the
# "side" field, and separately invented market="weather" for an
# off-topic question. Checking field/operator alone let both through --
# neither is a structurally invalid filter, they just query nonsense and
# silently return zero rows instead of surfacing the real problem. team
# and kickoff_date have no fixed enum (team names are open-ended; date
# format is checked separately, not against a value set).
#
# Sourced from predictions.market's own CHECK constraint (sql/schema.sql)
# and futbol.leagues -- kept in sync by hand, matching this project's
# existing "the two must be kept in sync by hand; nothing enforces this
# automatically" pattern for schema.sql vs. migrations.
ALLOWED_MARKET_VALUES = {
    "1X2", "BTTS", "TOTAL_GOALS", "CORNERS", "SOT", "PLAYER_GOALS", "PLAYER_SAVES",
    "MONEYLINE", "SPREAD", "TOTAL_POINTS", "PLAYER_PASS_YARDS", "PLAYER_RUSH_YARDS",
    "PLAYER_POINTS",
}
ALLOWED_LEAGUE_VALUES = {"EPL", "LA_LIGA", "MLS", "NBA", "NFL", "SERIE_A", "WC"}
ALLOWED_SIDE_VALUES = {"over", "under", "home", "draw", "away", "yes", "no"}
ALLOWED_OUTCOME_VALUES = {"hit", "miss"}  # v_graded_predictions already excludes 'void'

FIELD_VALUE_ALLOWLISTS: dict[str, set[str]] = {
    "market": ALLOWED_MARKET_VALUES,
    "league": ALLOWED_LEAGUE_VALUES,
    "side": ALLOWED_SIDE_VALUES,
    "outcome": ALLOWED_OUTCOME_VALUES,
}

# Bounds on the shape of a filter tree, independent of any single
# field/operator check -- without these, a proposal like nested "and"s
# 1000 deep, or one "and" with 10,000 conditions, is technically built
# entirely from allowlisted pieces but still a real resource-exhaustion
# vector once compiled into a query.
MAX_DEPTH = 4
MAX_CONDITIONS = 10


class FilterValidationError(ValueError):
    """Raised for any filter tree that fails validation -- message is
    safe to show the caller, it never echoes back untrusted structure."""


@dataclass(frozen=True)
class FilterCondition:
    field: str
    op: str
    value: str


@dataclass(frozen=True)
class FilterGroup:
    bool_op: str  # "and" | "or"
    children: tuple["FilterCondition | FilterGroup", ...]


FilterNode = FilterCondition | FilterGroup


def validate_filter(node: object, *, _depth: int = 0, _count: list[int] | None = None) -> FilterNode:
    """Validate an untrusted (Ollama-proposed) filter tree against the
    allowlist, raising FilterValidationError on the first problem found.
    Returns a tree of the frozen dataclasses above -- callers downstream
    (the compiler) only ever see already-validated structure, never the
    raw dict."""
    if _count is None:
        _count = [0]
    if _depth > MAX_DEPTH:
        raise FilterValidationError(f"filter nested too deeply (max depth {MAX_DEPTH})")
    if not isinstance(node, dict):
        raise FilterValidationError("filter node must be a JSON object")

    bool_keys = ALLOWED_BOOL_OPS & node.keys()
    if bool_keys:
        if len(node) != 1:
            raise FilterValidationError(
                "a boolean group must have exactly one key, 'and' or 'or'")
        bool_op = next(iter(bool_keys))
        children_raw = node[bool_op]
        if not isinstance(children_raw, list) or not children_raw:
            raise FilterValidationError(f"'{bool_op}' must be a non-empty list of filter nodes")
        children = tuple(
            validate_filter(c, _depth=_depth + 1, _count=_count) for c in children_raw)
        return FilterGroup(bool_op=bool_op, children=children)

    if set(node.keys()) != {"field", "op", "value"}:
        raise FilterValidationError(
            "a filter leaf must have exactly the keys 'field', 'op', 'value' "
            f"-- got {sorted(node.keys())}")

    field, op, value = node["field"], node["op"], node["value"]
    if field not in ALLOWED_FIELDS:
        raise FilterValidationError(
            f"field '{field}' is not allowed -- must be one of {sorted(ALLOWED_FIELDS)}")
    if op not in ALLOWED_OPERATORS:
        raise FilterValidationError(
            f"operator '{op}' is not allowed -- must be one of {sorted(ALLOWED_OPERATORS)}")
    # bool is an int subclass in Python -- explicitly excluded so a stray
    # `true`/`false` in the JSON doesn't silently become "True"/"False".
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise FilterValidationError("value must be a string or number")

    value_str = str(value)
    allowed_values = FIELD_VALUE_ALLOWLISTS.get(field)
    if allowed_values is not None:
        # Case-normalized: these are enum-like columns (market/league/
        # side/outcome codes), not free text, so "corners" and "CORNERS"
        # should both work rather than depending on Ollama matching case
        # exactly. Normalize to the canonical (uppercase-in-schema) form.
        normalized = value_str.upper() if field in ("market", "league") else value_str.lower()
        canonical = {v.upper() if field in ("market", "league") else v.lower(): v
                     for v in allowed_values}
        if normalized not in canonical:
            raise FilterValidationError(
                f"value '{value}' is not valid for field '{field}' "
                f"-- must be one of {sorted(allowed_values)}")
        value_str = canonical[normalized]
    elif field == "kickoff_date" and not _ISO_DATE.match(value_str):
        # No fixed value set (it's a date, not an enum), but still worth
        # rejecting garbage here rather than letting Postgres's implicit
        # text->date cast throw a DB-level error later for something
        # validation could have caught cleanly.
        raise FilterValidationError(
            f"value '{value}' is not a valid date for field 'kickoff_date' "
            "-- must be YYYY-MM-DD")
    elif field == "season" and not _SEASON.match(value_str):
        raise FilterValidationError(
            f"value '{value}' is not a valid season for field 'season' "
            "-- must be a year (2025) or split-year (2025-26)")

    _count[0] += 1
    if _count[0] > MAX_CONDITIONS:
        raise FilterValidationError(f"too many conditions (max {MAX_CONDITIONS})")

    return FilterCondition(field=field, op=op, value=value_str)


def compile_to_sql(node: FilterNode) -> tuple[str, list[str]]:
    """Deterministically compile an already-validated filter tree into a
    WHERE-clause fragment and its parameter list. Every value is a
    placeholder (%s) -- never string-interpolated -- so there is no
    injection surface even from a value that passed validation. Field
    names and operators are interpolated directly, but only ever reach
    this function already checked against ALLOWED_FIELDS/ALLOWED_OPERATORS
    by validate_filter, which every caller MUST run first."""
    if isinstance(node, FilterCondition):
        return f'"{node.field}" {node.op} %s', [node.value]
    if isinstance(node, FilterGroup):
        clauses: list[str] = []
        params: list[str] = []
        for child in node.children:
            clause, child_params = compile_to_sql(child)
            clauses.append(f"({clause})")
            params.extend(child_params)
        joiner = " AND " if node.bool_op == "and" else " OR "
        return joiner.join(clauses), params
    raise TypeError(f"unexpected filter node type: {type(node)!r}")  # pragma: no cover


def validate_and_compile(raw_filter: object) -> tuple[str, list[str]]:
    """Convenience entry point: validate then compile in one call."""
    return compile_to_sql(validate_filter(raw_filter))
