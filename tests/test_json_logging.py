"""
Regression tests for ops/json_logging.py -- the structured logging
Promtail (k8s/promtail.yaml) parses to promote level/job/etc. to real
Loki labels.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ops.json_logging import configure_json_logging


def test_basic_fields_present(capsys):
    log = configure_json_logging("test_job")
    log.info("hello")
    out = capsys.readouterr().out
    payload = json.loads(out.strip())
    assert payload["level"] == "INFO"
    assert payload["job"] == "test_job"
    assert payload["message"] == "hello"
    assert "timestamp" in payload


def test_extra_fields_merged_into_payload(capsys):
    log = configure_json_logging("test_job")
    log.info("fixture skipped", extra={"reason": "already slated", "league": "MLS"})
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["reason"] == "already slated"
    assert payload["league"] == "MLS"


def test_exception_traceback_included(capsys):
    log = configure_json_logging("test_job")
    try:
        raise ValueError("boom")
    except ValueError:
        log.error("failed", exc_info=True)
    payload = json.loads(capsys.readouterr().out.strip())
    assert "ValueError: boom" in payload["exc_info"]


def test_output_is_one_json_object_per_line(capsys):
    log = configure_json_logging("test_job")
    log.info("first")
    log.info("second")
    lines = capsys.readouterr().out.strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # doesn't raise


def test_other_module_loggers_inherit_the_json_handler(capsys):
    """logging.basicConfig-style usage elsewhere in this codebase does
    `logging.getLogger(__name__)` and expects the root handler set up by
    configure_json_logging() to apply to it too."""
    configure_json_logging("test_job")
    other = logging.getLogger("some.other.module")
    other.info("from another module")
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["logger"] == "some.other.module"
    assert payload["job"] == "test_job"
