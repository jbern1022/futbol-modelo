"""
Point-in-time snapshots (Todoist 6hf57MCf77fRr9Xf): for each saved prediction, the model
version, cutoff, how fresh the inputs were, the feature values, what was missing, and
whether a real referee was known. Post-cutoff information is rejected, never inserted.
"""
import math
from datetime import datetime, timedelta, timezone

import pytest

from predictions.snapshot import build_snapshot, record_snapshots

CUTOFF = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
KICKOFF = CUTOFF + timedelta(days=2)
FEATS = ["corners_for_r5", "xg_for_r5", "rest_days", "is_home"]


def _snap(**kw):
    base = dict(market="CORNERS", features={"corners_for_r5": 6.2, "xg_for_r5": 1.4, "rest_days": 7},
                feature_cols=FEATS, is_home=True, cutoff=CUTOFF, kickoff=KICKOFF,
                form_meta={"inputs_through": CUTOFF - timedelta(days=3), "n_games": 5, "window_days": 90},
                model_tag="v4")
    base.update(kw)
    return build_snapshot(**base)


def test_records_cutoff_freshness_and_only_the_model_feature_columns():
    s = _snap(features={"corners_for_r5": 6.2, "xg_for_r5": 1.4, "rest_days": 7, "sot_for_r5": 3.0})
    assert s["cutoff_at"] == CUTOFF and s["kickoff_at"] == KICKOFF
    assert s["inputs_through"] == CUTOFF - timedelta(days=3) and s["n_games"] == 5
    assert s["feature_values"] == {"corners_for_r5": 6.2, "xg_for_r5": 1.4, "rest_days": 7, "is_home": 1}
    assert s["model_tag"] == "v4" and s["schema_version"] == 1


def test_missing_and_nan_features_are_listed_and_stored_as_null():
    s = _snap(features={"corners_for_r5": float("nan"), "rest_days": 7})
    assert s["feature_values"]["corners_for_r5"] is None and s["feature_values"]["xg_for_r5"] is None
    assert s["missing_features"] == ["corners_for_r5", "xg_for_r5"]
    assert not any(isinstance(v, float) and math.isnan(v) for v in s["feature_values"].values())


def test_numpy_scalars_become_plain_json_serialisable_python():
    import json

    import numpy as np
    s = _snap(features={"corners_for_r5": np.float64(6.5), "xg_for_r5": np.float64("nan"), "rest_days": np.int64(6)})
    assert type(s["feature_values"]["rest_days"]) is int and type(s["feature_values"]["corners_for_r5"]) is float
    assert s["missing_features"] == ["xg_for_r5"]
    json.dumps(s["feature_values"])


def test_post_cutoff_inputs_are_rejected():
    with pytest.raises(ValueError, match="after the cutoff"):
        _snap(form_meta={"inputs_through": CUTOFF + timedelta(hours=1), "n_games": 5, "window_days": 90})


def test_cutoff_must_precede_kickoff():
    with pytest.raises(ValueError, match="before kickoff"):
        _snap(cutoff=KICKOFF)


def test_cards_with_no_known_referee_records_the_fallback_not_a_guess():
    s = _snap(market="CARDS", referee=None, referee_used="league_average_fallback")
    assert s["referee_known"] is False and s["referee_name"] is None
    assert s["referee_used"] == "league_average_fallback"


def test_cards_with_a_known_referee_records_it_even_if_the_model_ignored_it():
    s = _snap(market="CARDS", referee="Paul Tierney", referee_used="league_average_fallback")
    assert s["referee_known"] is True and s["referee_name"] == "Paul Tierney"


def test_non_cards_markets_have_no_referee_fields_set():
    s = _snap()
    assert s["referee_known"] is None and s["referee_name"] is None and s["referee_used"] is None


class _Cur:
    def __init__(self):
        self.calls, self.rowcount = [], 1

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self):
        self.cur, self.commits = _Cur(), 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


class _Inf:
    def __init__(self, snapshot, **kw):
        self.snapshot = snapshot
        self.market, self.subject_team_id, self.subject_player_id = kw.get("market", "CORNERS"), 31, None
        self.side, self.line = "over", 4.5


def test_record_writes_one_row_per_prediction_that_has_a_snapshot_and_skips_the_rest():
    conn = _Conn()
    n = record_snapshots(conn, match_id=10, model_version_id=3,
                         slate=[_Inf(_snap()), _Inf(None), _Inf(_snap())])
    assert n == 2 and len(conn.cur.calls) == 2 and conn.commits == 1
    sql, params = conn.cur.calls[0]
    assert "INSERT INTO futbol.prediction_snapshots" in sql and "ON CONFLICT (prediction_id) DO NOTHING" in sql
    assert "FROM futbol.predictions" in sql
    assert params[-7:] == (10, 3, "CORNERS", 31, None, "over", 4.5)


def test_current_form_reports_input_freshness_through_meta_out():
    import sys
    sys.path.insert(0, "scripts")
    from generate_slate import current_form

    ko = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
    games = [ko - timedelta(days=d) for d in (5, 12, 19, 26, 33)]

    class Cur:
        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return [(6, 14, 5, 1.5, 11, 2, 0, 4, 10, 3, 1.0, g) for g in games]

    meta: dict = {}
    form = current_form(Cur(), 7, ko, meta_out=meta)
    assert form["corners_for_r5"] == 6 and meta == {
        "inputs_through": games[0], "n_games": 5, "window_days": 90}
    assert current_form(Cur(), 7, ko) == form  # meta_out is optional and changes nothing
