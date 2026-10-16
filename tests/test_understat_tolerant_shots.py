"""read_shots_tolerant: one unparseable Understat match page must not abort
the shot load (found 2026-10-14: Bundesliga game 27930, empty rosters)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from backfill_understat_shots import read_shots_tolerant  # noqa: E402


class FakeUnderstat:
    def __init__(self, bad):
        self.bad = set(bad)
        self.calls = []

    def read_shot_events(self, match_id=None):
        ids = match_id if isinstance(match_id, list) else [match_id]
        self.calls.append(list(ids))
        if self.bad & set(ids):
            raise AttributeError("'list' object has no attribute 'values'")
        return pd.DataFrame({"game_id": ids, "xg": [0.1] * len(ids)})


def test_all_good_pages_are_read_in_chunks_with_no_skips():
    us = FakeUnderstat(bad=[])
    shots, skipped = read_shots_tolerant(us, range(1, 61), chunk_size=25)
    assert skipped == []
    assert sorted(shots.game_id) == list(range(1, 61))
    assert len(us.calls) == 3  # 25 + 25 + 10


def test_one_bad_page_is_skipped_and_the_rest_of_its_chunk_is_kept():
    us = FakeUnderstat(bad=[27930])
    ids = list(range(27920, 27945))  # one chunk containing the bad id
    shots, skipped = read_shots_tolerant(us, ids, chunk_size=25)
    assert [g for g, _ in skipped] == [27930]
    assert "AttributeError" in skipped[0][1]
    assert sorted(shots.game_id) == [g for g in ids if g != 27930]


def test_every_page_bad_returns_an_empty_frame_and_all_skips():
    us = FakeUnderstat(bad=[1, 2, 3])
    shots, skipped = read_shots_tolerant(us, [1, 2, 3], chunk_size=25)
    assert shots.empty
    assert [g for g, _ in skipped] == [1, 2, 3]


def test_numpy_style_ids_are_accepted():
    import numpy as np
    us = FakeUnderstat(bad=[])
    shots, skipped = read_shots_tolerant(us, np.array([5.0, 6.0, 7.0]), chunk_size=25)
    assert skipped == [] and sorted(shots.game_id) == [5, 6, 7]
