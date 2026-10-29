"""
Point-in-time snapshots of what a prediction was built from (Todoist 6hf57MCf77fRr9Xf).

One append-only row in futbol.prediction_snapshots per saved prediction: the cutoff
(when the slate was locked), how fresh the inputs were, the feature values the model saw,
which were missing, and (CARDS) whether a real referee was known. It exists so a later
experiment can say what was knowable at slate time instead of re-deriving it from today's
tables. Post-cutoff information is rejected, never written; history is never rewritten.

Kept out of predictions.context on purpose: the web "why" panel renders every context key
as a number, so a nested object there would break fixture pages.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1


def _clean(v: Any) -> Any:
    """NaN -> None, numpy scalars -> plain Python (json.dumps rejects np.int64)."""
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        v = v.item()
    return None if isinstance(v, float) and math.isnan(v) else v


def build_snapshot(*, market: str, features: dict, feature_cols: list[str], is_home: bool,
                   cutoff: datetime, kickoff: datetime, form_meta: dict, model_tag: str,
                   referee: str | None = None, referee_used: str | None = None) -> dict:
    if cutoff >= kickoff:
        raise ValueError("snapshot cutoff must be before kickoff")
    through = form_meta.get("inputs_through")
    if through is not None and through > cutoff:
        raise ValueError(f"inputs run through {through}, which is after the cutoff {cutoff}")
    row = {**features, "is_home": int(is_home)}
    values = {c: _clean(row.get(c)) for c in feature_cols}
    is_cards = market == "CARDS"
    return {
        "schema_version": SCHEMA_VERSION,
        "cutoff_at": cutoff, "kickoff_at": kickoff, "inputs_through": through,
        "n_games": form_meta.get("n_games"), "window_days": form_meta.get("window_days"),
        "model_tag": model_tag, "feature_values": values,
        "missing_features": [c for c, v in values.items() if v is None],
        "referee_known": (referee is not None) if is_cards else None,
        "referee_name": referee if is_cards else None,
        "referee_used": referee_used if is_cards else None,
    }


INSERT_SQL = """
INSERT INTO futbol.prediction_snapshots
    (prediction_id, schema_version, cutoff_at, kickoff_at, inputs_through, n_games, window_days,
     model_tag, feature_values, missing_features, referee_known, referee_name, referee_used)
SELECT p.prediction_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
FROM futbol.predictions p
WHERE p.match_id = %s AND p.model_version_id = %s AND p.market = %s
  AND COALESCE(p.subject_team_id, -1) = COALESCE(%s, -1)
  AND COALESCE(p.subject_player_id, -1) = COALESCE(%s, -1)
  AND COALESCE(p.side, '') = COALESCE(%s, '')
  AND COALESCE(p.line, -9999) = COALESCE(%s, -9999)
ON CONFLICT (prediction_id) DO NOTHING
"""


def record_snapshots(conn, match_id: int, model_version_id: int, slate: list) -> int:
    """Write the snapshot of every slate entry that carries one. Call after persist_slate."""
    from psycopg2.extras import Json
    written = 0
    with conn.cursor() as cur:
        for inf in slate:
            s = getattr(inf, "snapshot", None)
            if s is None:
                continue
            cur.execute(INSERT_SQL, (
                s["schema_version"], s["cutoff_at"], s["kickoff_at"], s["inputs_through"], s["n_games"],
                s["window_days"], s["model_tag"], Json(s["feature_values"]), s["missing_features"],
                s["referee_known"], s["referee_name"], s["referee_used"],
                match_id, model_version_id, inf.market, inf.subject_team_id, inf.subject_player_id,
                inf.side, float(inf.line) if inf.line is not None else None))
            written += max(cur.rowcount, 0)
    conn.commit()
    return written
