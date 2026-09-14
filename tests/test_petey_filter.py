"""
Tests for Petey v2's JSON filter validator + compiler (api/petey_filter.py).
Pure logic, no database needed -- always runs.

This is the safety-critical piece the whole free-text -> JSON filter
design rests on ("safety comes from the validator, not from trusting
the model to behave"), so coverage here is deliberately adversarial,
not just happy-path.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from petey_filter import (
    FilterCondition,
    FilterGroup,
    FilterValidationError,
    compile_to_sql,
    validate_and_compile,
    validate_filter,
)


# ---------- valid filters ----------

def test_valid_leaf():
    node = validate_filter({"field": "market", "op": "=", "value": "CORNERS"})
    assert node == FilterCondition(field="market", op="=", value="CORNERS")


def test_valid_and_group():
    node = validate_filter({
        "and": [
            {"field": "market", "op": "=", "value": "CORNERS"},
            {"field": "league", "op": "=", "value": "MLS"},
        ]
    })
    assert isinstance(node, FilterGroup)
    assert node.bool_op == "and"
    assert len(node.children) == 2


def test_valid_nested_or_inside_and():
    node = validate_filter({
        "and": [
            {"field": "market", "op": "=", "value": "CORNERS"},
            {"or": [
                {"field": "league", "op": "=", "value": "MLS"},
                {"field": "league", "op": "=", "value": "EPL"},
            ]},
        ]
    })
    assert isinstance(node, FilterGroup)
    assert isinstance(node.children[1], FilterGroup)


def test_numeric_value_coerced_to_string():
    # numbers are allowed in the JSON, stored as strings internally
    # since every allowlisted field is text/date, never compared as a
    # raw number. team has no value allowlist, so this isolates the
    # coercion behavior from the separate per-field value checks.
    node = validate_filter({"field": "team", "op": ">", "value": 2025})
    assert node == FilterCondition(field="team", op=">", value="2025")


# ---------- rejected: field/operator allowlist ----------

def test_rejects_field_not_on_allowlist():
    with pytest.raises(FilterValidationError, match="field"):
        validate_filter({"field": "probability", "op": "=", "value": "0.9"})


def test_rejects_field_targeting_a_different_table():
    # the actual point of the allowlist: no amount of "this looks like
    # a real column" gets through if it isn't explicitly listed.
    with pytest.raises(FilterValidationError):
        validate_filter({"field": "prediction_id", "op": "=", "value": "1"})


# ---------- rejected: per-field value allowlist ----------
# Found necessary through live testing against real Ollama output, not
# hypothetically -- both of the next two are transcripts of actual bugs
# a first-draft prompt produced.

def test_rejects_market_code_in_the_wrong_field():
    # real live bug: asked "shots on target hits in Serie A", got back
    # {"field": "side", "op": "=", "value": "SOT"} -- SOT is a market
    # code, not a valid side. Structurally fine (allowlisted field,
    # allowlisted op, string value) but semantically nonsense -- would
    # have silently compiled to a query that just finds zero rows.
    with pytest.raises(FilterValidationError, match="not valid for field 'side'"):
        validate_filter({"field": "side", "op": "=", "value": "SOT"})


def test_rejects_invented_market_value():
    # real live bug: an off-topic question ("what's the weather like")
    # got back {"field": "market", "op": "=", "value": "weather"}.
    with pytest.raises(FilterValidationError, match="not valid for field 'market'"):
        validate_filter({"field": "market", "op": "=", "value": "weather"})


def test_market_value_is_case_normalized():
    # enum-like fields shouldn't depend on Ollama matching case exactly.
    node = validate_filter({"field": "market", "op": "=", "value": "corners"})
    assert node.value == "CORNERS"


def test_league_value_is_case_normalized():
    node = validate_filter({"field": "league", "op": "=", "value": "mls"})
    assert node.value == "MLS"


def test_outcome_value_is_case_normalized():
    node = validate_filter({"field": "outcome", "op": "=", "value": "HIT"})
    assert node.value == "hit"


def test_rejects_invalid_outcome_value():
    with pytest.raises(FilterValidationError, match="not valid for field 'outcome'"):
        validate_filter({"field": "outcome", "op": "=", "value": "voided"})


def test_rejects_invalid_league_value():
    with pytest.raises(FilterValidationError, match="not valid for field 'league'"):
        validate_filter({"field": "league", "op": "=", "value": "PREMIER_LEAGUE"})


def test_team_field_has_no_value_allowlist():
    # team names are open-ended -- any string passes structural
    # validation (the query just returns zero rows for a nonexistent
    # team, which is correct/honest behavior, not a bug to prevent).
    node = validate_filter({"field": "team", "op": "=", "value": "Some Made Up FC"})
    assert node.value == "Some Made Up FC"


def test_kickoff_date_accepts_iso_format():
    node = validate_filter({"field": "kickoff_date", "op": ">=", "value": "2026-01-01"})
    assert node.value == "2026-01-01"


def test_kickoff_date_rejects_non_iso_format():
    with pytest.raises(FilterValidationError, match="not a valid date"):
        validate_filter({"field": "kickoff_date", "op": "=", "value": "January 1st"})


def test_kickoff_date_rejects_sql_injection_shaped_value():
    with pytest.raises(FilterValidationError, match="not a valid date"):
        validate_filter({"field": "kickoff_date", "op": "=", "value": "2026-01-01'; DROP TABLE x; --"})


def test_season_accepts_bare_year():
    node = validate_filter({"field": "season", "op": "=", "value": "2025"})
    assert node.value == "2025"


def test_season_accepts_split_year():
    node = validate_filter({"field": "season", "op": "=", "value": "2025-26"})
    assert node.value == "2025-26"


def test_season_rejects_relative_phrase():
    # real live bug: "this season" was Ollama's literal proposed value.
    with pytest.raises(FilterValidationError, match="not a valid season"):
        validate_filter({"field": "season", "op": "=", "value": "this season"})


def test_season_rejects_nonsense_small_integer():
    # real live bug: another question produced season="1".
    with pytest.raises(FilterValidationError, match="not a valid season"):
        validate_filter({"field": "season", "op": "=", "value": "1"})


def test_rejects_operator_not_on_allowlist():
    with pytest.raises(FilterValidationError, match="operator"):
        validate_filter({"field": "market", "op": "!=", "value": "CORNERS"})


def test_rejects_sql_keyword_disguised_as_operator():
    with pytest.raises(FilterValidationError, match="operator"):
        validate_filter({"field": "market", "op": "OR 1=1; --", "value": "x"})


# ---------- rejected: shape ----------

def test_rejects_non_dict_node():
    with pytest.raises(FilterValidationError, match="object"):
        validate_filter("not a dict")


def test_rejects_leaf_missing_a_key():
    with pytest.raises(FilterValidationError):
        validate_filter({"field": "market", "op": "="})


def test_rejects_leaf_with_extra_key():
    with pytest.raises(FilterValidationError):
        validate_filter({"field": "market", "op": "=", "value": "CORNERS", "extra": 1})


def test_rejects_group_with_extra_key_alongside_and():
    with pytest.raises(FilterValidationError):
        validate_filter({"and": [{"field": "market", "op": "=", "value": "CORNERS"}], "or": []})


def test_rejects_empty_and_list():
    with pytest.raises(FilterValidationError, match="non-empty"):
        validate_filter({"and": []})


def test_rejects_and_value_that_is_not_a_list():
    with pytest.raises(FilterValidationError):
        validate_filter({"and": {"field": "market", "op": "=", "value": "CORNERS"}})


def test_rejects_boolean_value():
    # bool is an int subclass in Python -- must be explicitly excluded
    # or `true` silently becomes the string "True".
    with pytest.raises(FilterValidationError, match="string or number"):
        validate_filter({"field": "market", "op": "=", "value": True})


def test_rejects_null_value():
    with pytest.raises(FilterValidationError, match="string or number"):
        validate_filter({"field": "market", "op": "=", "value": None})


def test_rejects_dict_value():
    with pytest.raises(FilterValidationError, match="string or number"):
        validate_filter({"field": "market", "op": "=", "value": {"nested": "object"}})


# ---------- rejected: resource-exhaustion bounds ----------

def test_rejects_excessive_nesting_depth():
    node = {"field": "market", "op": "=", "value": "CORNERS"}
    for _ in range(10):
        node = {"and": [node]}
    with pytest.raises(FilterValidationError, match="nested too deeply"):
        validate_filter(node)


def test_rejects_too_many_conditions():
    conditions = [{"field": "team", "op": "=", "value": f"Team{i}"} for i in range(20)]
    with pytest.raises(FilterValidationError, match="too many conditions"):
        validate_filter({"and": conditions})


def test_allows_exactly_the_condition_limit():
    from petey_filter import MAX_CONDITIONS
    conditions = [{"field": "team", "op": "=", "value": f"Team{i}"} for i in range(MAX_CONDITIONS)]
    validate_filter({"and": conditions})  # should not raise


# ---------- compiler: SQL shape + injection safety ----------

def test_compile_leaf_produces_placeholder_not_literal():
    sql, params = compile_to_sql(FilterCondition(field="market", op="=", value="CORNERS"))
    assert sql == '"market" = %s'
    assert params == ["CORNERS"]
    assert "CORNERS" not in sql  # the value never lands in the SQL text itself


def test_compile_and_group():
    sql, params = compile_to_sql(FilterGroup(
        bool_op="and",
        children=(
            FilterCondition(field="market", op="=", value="CORNERS"),
            FilterCondition(field="league", op="=", value="MLS"),
        ),
    ))
    assert sql == '("market" = %s) AND ("league" = %s)'
    assert params == ["CORNERS", "MLS"]


def test_compile_or_group():
    sql, params = compile_to_sql(FilterGroup(
        bool_op="or",
        children=(
            FilterCondition(field="league", op="=", value="MLS"),
            FilterCondition(field="league", op="=", value="EPL"),
        ),
    ))
    assert " OR " in sql
    assert params == ["MLS", "EPL"]


def test_adversarial_value_is_never_interpolated_into_sql_text():
    # The actual point of parameterization: even a value crafted to look
    # like it's trying to break out of the query stays a plain string
    # that only ever reaches the DB as a bound parameter, never as text
    # substituted into the SQL string that gets executed.
    payload = "'; DROP TABLE futbol.predictions; --"
    node = validate_filter({"field": "team", "op": "=", "value": payload})
    sql, params = compile_to_sql(node)
    assert payload not in sql
    assert sql == '"team" = %s'
    assert params == [payload]


def test_adversarial_value_via_validate_and_compile_end_to_end():
    payload = "x' OR '1'='1"
    sql, params = validate_and_compile({"field": "team", "op": "=", "value": payload})
    assert payload not in sql
    assert params == [payload]


def test_field_and_operator_are_never_taken_from_unvalidated_input():
    # compile_to_sql trusts its input completely (by contract, callers
    # must validate first) -- confirm validate_and_compile actually
    # enforces that ordering rather than skipping validation.
    with pytest.raises(FilterValidationError):
        validate_and_compile({"field": "prediction_id; DROP TABLE x; --", "op": "=", "value": "1"})
