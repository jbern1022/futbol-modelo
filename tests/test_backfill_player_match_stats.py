"""run_backfill() with a fake connection and an injected loader: no DB, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from backfill_player_match_stats import COMMIT_EVERY, run_backfill  # noqa: E402


class FakeConn:
    def __init__(self):
        self.commits = self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def rows(n):
    return [(i, 1000 + i, 1, 2, 33, "2023-24") for i in range(1, n + 1)]


def test_loads_every_row_and_commits_at_the_end():
    conn, seen = FakeConn(), []
    loaded, failed, aborted = run_backfill(
        conn, None, rows(3), load=lambda s, c, mid, *a: seen.append(mid))
    assert (loaded, failed, aborted) == (3, 0, False)
    assert seen == [1, 2, 3]
    assert conn.commits == 1


def test_commits_periodically():
    conn = FakeConn()
    run_backfill(conn, None, rows(COMMIT_EVERY * 2), load=lambda *a: None)
    assert conn.commits == 3  # two periodic + the final one


def test_a_single_failure_is_skipped_and_the_run_continues():
    def load(s, c, match_id, *a):
        if match_id == 2:
            raise RuntimeError("boom")

    conn = FakeConn()
    loaded, failed, aborted = run_backfill(conn, None, rows(4), load=load)
    assert (loaded, failed, aborted) == (3, 1, False)
    assert conn.rollbacks == 1


def test_consecutive_failures_abort_the_run_early():
    calls = []

    def load(s, c, match_id, *a):
        calls.append(match_id)
        raise RuntimeError("quota exhausted")

    loaded, failed, aborted = run_backfill(
        FakeConn(), None, rows(50), load=load, max_consecutive_failures=3)
    assert (loaded, failed, aborted) == (0, 3, True)
    assert calls == [1, 2, 3]  # did not keep burning calls


def test_a_success_resets_the_failure_streak():
    def load(s, c, match_id, *a):
        if match_id in (1, 2, 4, 5):
            raise RuntimeError("flaky")

    loaded, failed, aborted = run_backfill(
        FakeConn(), None, rows(6), load=load, max_consecutive_failures=3)
    assert aborted is False
    assert (loaded, failed) == (2, 4)
