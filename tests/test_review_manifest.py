"""
Reviewer manifest (Todoist 6hWgXxQj4Q9x65c7): a read-only, machine-readable statement of what was
evaluated -- code version, library versions, schema version, model versions, ledger cohorts with their
ADR-020 evidence-gate status, and data coverage. Pure parts are tested directly; the database part runs
against a throwaway Postgres (FUTBOL_TEST_DSN) that already has sql/schema.sql.
"""
import json
import os
import sys

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from build_review_manifest import build_manifest, canonical_hash, cohort_summary, library_versions  # noqa: E402

TEST_DSN = os.environ.get("FUTBOL_TEST_DSN")


def test_canonical_hash_ignores_key_order_and_formatting():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})
    assert len(canonical_hash({})) == 64


def test_library_versions_report_the_libraries_that_decide_results():
    v = library_versions()
    assert {"python", "numpy", "pandas", "scipy", "scikit-learn", "lightgbm", "psycopg2"} <= set(v)
    assert all(isinstance(x, str) and x for x in v.values())


def test_cohort_summary_applies_the_adr_020_gates_and_labels_pooling():
    probs = [0.65] * 800
    hits = [1] * 520 + [0] * 280  # exactly 65%
    s = cohort_summary("EPL", "CORNERS", probs, hits)
    assert s["league"] == "EPL" and s["market"] == "CORNERS" and s["n_graded"] == 800
    assert s["status"] == "EVALUATED" and s["tolerance_regime"] == "interim"
    assert s["pools_model_versions"] is True
    assert s["bands"][0]["n"] == 800 and abs(s["bands"][0]["gap"]) < 1e-9


def test_cohort_summary_below_the_gates_is_insufficient_evidence():
    s = cohort_summary("NBA", "TOTAL_POINTS", [0.6] * 100, [1] * 60 + [0] * 40)
    assert s["status"] == "INSUFFICIENT_EVIDENCE" and s["bands"][0]["evaluated"] is False


@pytest.mark.skipif(not TEST_DSN, reason="FUTBOL_TEST_DSN not set (throwaway database)")
def test_manifest_on_a_real_schema_is_complete_json_and_read_only():
    conn = psycopg2.connect(TEST_DSN)
    try:
        m = build_manifest(conn)
        json.dumps(m, default=str)  # must serialise
        assert {"generated_at", "code", "libraries", "database", "model_versions", "ledger_cohorts",
                "data_coverage", "snapshots", "known_limitations"} <= set(m)
        assert m["database"]["read_only_session"] is True
        assert isinstance(m["ledger_cohorts"], list) and isinstance(m["known_limitations"], list)
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error):
                cur.execute("CREATE TABLE futbol.should_not_exist (x int)")
    finally:
        conn.rollback()
        conn.close()
