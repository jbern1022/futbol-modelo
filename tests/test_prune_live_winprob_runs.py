"""prune() against a fake cursor: dry run must never issue the DELETE."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prune_live_winprob_runs import JOB_NAME_LIKE, prune  # noqa: E402


class FakeCursor:
    def __init__(self, count):
        self.count, self.executed = count, []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return (self.count,)


def test_dry_run_counts_but_never_deletes():
    cur = FakeCursor(120)
    assert prune(cur, 30, execute=False) == 120
    assert not any("DELETE" in sql for sql, _ in cur.executed)


def test_execute_deletes_only_live_winprob_rows():
    cur = FakeCursor(120)
    assert prune(cur, 30, execute=True) == 120
    deletes = [(sql, p) for sql, p in cur.executed if "DELETE" in sql]
    assert len(deletes) == 1
    assert deletes[0][1] == (JOB_NAME_LIKE, "30")
    assert JOB_NAME_LIKE == "live_winprob:%"


def test_execute_with_nothing_eligible_skips_the_delete():
    cur = FakeCursor(0)
    assert prune(cur, 30, execute=True) == 0
    assert not any("DELETE" in sql for sql, _ in cur.executed)


def test_rejects_a_zero_retention_window():
    with pytest.raises(ValueError):
        prune(FakeCursor(0), 0, execute=True)
