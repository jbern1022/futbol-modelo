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

from dataclasses import dataclass

ALLOWED_FIELDS = {"market", "league", "team", "season", "side", "outcome", "kickoff_date"}
ALLOWED_OPERATORS = {"=", ">", "<", ">=", "<="}
ALLOWED_BOOL_OPS = {"and", "or"}

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

    _count[0] += 1
    if _count[0] > MAX_CONDITIONS:
        raise FilterValidationError(f"too many conditions (max {MAX_CONDITIONS})")

    return FilterCondition(field=field, op=op, value=str(value))


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
