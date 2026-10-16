"""
Trailing league offset (scripts/experiment_props_time_offset.py): it must use
only strictly earlier results in the same league, honour the window, and fall
back to the pool mean when there is too little history. Synthetic data only.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "dixon-coles", "src"))

from experiment_props_time_offset import trailing_offsets  # noqa: E402

T0 = pd.Timestamp("2025-01-01", tz="UTC")


def _frame(rows):
    """rows: [(league, day, y)] -> frame with the columns trailing_offsets reads."""
    return pd.DataFrame({"league": [r[0] for r in rows],
                         "kickoff": [T0 + pd.Timedelta(days=r[1]) for r in rows],
                         "y": [float(r[2]) for r in rows]})


def test_offset_is_the_mean_of_the_previous_window_rows():
    df = _frame([("A", d, y) for d, y in enumerate([2, 4, 6, 8, 10, 12])])
    off = trailing_offsets(df, fallback=99.0, window=3, min_rows=1)
    assert off.iloc[0] == 99.0                  # no history yet
    assert off.iloc[1] == 2.0                   # [2]
    assert off.iloc[3] == (2 + 4 + 6) / 3       # three previous
    assert off.iloc[5] == (6 + 8 + 10) / 3      # window slides, current row excluded


def test_rows_with_the_same_kickoff_do_not_see_each_other():
    df = _frame([("A", 0, 1), ("A", 1, 5), ("A", 1, 9), ("A", 2, 3)])
    off = trailing_offsets(df, fallback=99.0, window=10, min_rows=1)
    assert off.iloc[1] == 1.0 and off.iloc[2] == 1.0   # both day-1 rows see only day 0
    assert off.iloc[3] == (1 + 5 + 9) / 3


def test_too_little_history_falls_back_to_the_pool_mean():
    df = _frame([("A", d, 4) for d in range(5)])
    off = trailing_offsets(df, fallback=7.5, window=10, min_rows=3)
    assert list(off.iloc[:3]) == [7.5, 7.5, 7.5]       # fewer than 3 prior rows
    assert off.iloc[3] == 4.0 and off.iloc[4] == 4.0


def test_leagues_do_not_mix():
    df = _frame([("A", 0, 2), ("B", 0, 10), ("A", 1, 4), ("B", 1, 20), ("A", 2, 0), ("B", 2, 0)])
    off = trailing_offsets(df, fallback=99.0, window=10, min_rows=1)
    assert off.iloc[4] == 3.0     # A: mean(2, 4)
    assert off.iloc[5] == 15.0    # B: mean(10, 20)


def test_the_offset_never_uses_the_future():
    rng = np.random.default_rng(0)
    rows = [("A", d, rng.integers(0, 9)) for d in range(40)]
    base = trailing_offsets(_frame(rows), fallback=5.0, window=8, min_rows=2)
    changed = rows[:30] + [("A", d, 1000) for d in range(30, 40)]
    after = trailing_offsets(_frame(changed), fallback=5.0, window=8, min_rows=2)
    assert np.allclose(base.iloc[:31], after.iloc[:31])   # rows up to day 30 see only days < their own
    assert not np.allclose(base.iloc[31:], after.iloc[31:])


def test_result_is_aligned_to_the_input_index_when_unsorted():
    df = _frame([("A", 2, 6), ("A", 0, 2), ("A", 1, 4)])
    off = trailing_offsets(df, fallback=99.0, window=10, min_rows=1)
    assert off.iloc[1] == 99.0 and off.iloc[2] == 2.0 and off.iloc[0] == 3.0
