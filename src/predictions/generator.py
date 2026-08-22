"""
Inference generator: turns model outputs into the per-match slate of
~20 inferences, written to the immutable prediction ledger BEFORE kickoff.

Selection policy (v1):
  - Pull candidate inferences from every market the models cover.
  - Keep those whose calibrated probability falls in the target band
    (default 0.60–0.75) — these are the "bold but likely" claims.
  - Also log a handful of high-confidence anchors (>0.80) and one or two
    speculative (<0.45) picks: you need the full probability range
    represented or the calibration curve has no support at the tails.
  - Rank by |edge| where edge = calibrated_p - historical base rate for
    that market/line, so the slate favors *informative* claims over
    trivially true ones.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from psycopg2.extras import Json

TARGET_BAND = (0.60, 0.75)
SLATE_SIZE = 20


@dataclass
class Inference:
    market: str
    statement: str
    line: float | None
    side: str
    probability: float
    subject_team_id: int | None = None
    subject_player_id: int | None = None
    base_rate: float | None = None      # historical frequency of this claim
    context: dict | None = None         # form inputs the model saw ("why" panel)

    @property
    def edge(self) -> float:
        return abs(self.probability - (self.base_rate or 0.5))


def build_slate(candidates: list[Inference],
                band: tuple[float, float] = TARGET_BAND,
                size: int = SLATE_SIZE) -> list[Inference]:
    lo, hi = band
    in_band = [c for c in candidates if lo <= c.probability <= hi]
    anchors = [c for c in candidates if c.probability > 0.80]
    specs = [c for c in candidates if c.probability < 0.45]

    in_band.sort(key=lambda c: -c.edge)
    anchors.sort(key=lambda c: -c.edge)
    specs.sort(key=lambda c: -c.edge)

    slate = in_band[: size - 5] + anchors[:3] + specs[:2]
    seen, final = set(), []
    for c in slate:
        key = (c.market, c.subject_team_id, c.subject_player_id, c.line, c.side)
        if key not in seen:
            seen.add(key)
            final.append(c)

    if len(final) < size:
        leftovers = [c for c in candidates
                    if (c.market, c.subject_team_id, c.subject_player_id,
                        c.line, c.side) not in seen]
        leftovers.sort(key=lambda c: -c.edge)
        for c in leftovers:
            key = (c.market, c.subject_team_id, c.subject_player_id, c.line, c.side)
            if key not in seen:
                seen.add(key)
                final.append(c)
            if len(final) >= size:
                break

    return final[:size]


def _sanitize_context(context: dict | None) -> dict | None:
    """json.dumps happily emits literal NaN for a NaN float, which is not
    valid JSON -- Postgres's JSONB parser rejects it and the whole INSERT
    fails. current_form()'s rolling .mean() can produce NaN on a sparse
    data window, so this isn't just theoretical."""
    if context is None:
        return None
    return {k: (None if isinstance(v, float) and math.isnan(v) else v)
            for k, v in context.items()}


def persist_slate(conn, match_id: int, model_version_id: int,
                  slate: list[Inference]) -> int:
    """
    Insert into futbol.predictions. Trigger enforces pre-kickoff lock.
    Uses ON CONFLICT DO NOTHING so re-running generation against an
    already-slated match inserts only genuinely new rows instead of
    aborting the whole batch on the first pre-existing one.
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    with conn.cursor() as cur:
        for inf in slate:
            cur.execute(
                """
                INSERT INTO futbol.predictions
                    (match_id, model_version_id, market, subject_team_id,
                     subject_player_id, statement, line, side, probability,
                     created_at, locked_at, context)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (match_id, model_version_id, market,
                             COALESCE(subject_team_id, '-1'::integer),
                             COALESCE(subject_player_id, '-1'::integer),
                             COALESCE(side, ''::text),
                             COALESCE(line, '-9999'::integer::numeric))
                DO NOTHING
                """,
                (match_id, model_version_id, inf.market, inf.subject_team_id,
                 inf.subject_player_id, inf.statement, inf.line, inf.side,
                 round(inf.probability, 5), now, now,
                 Json(_sanitize_context(inf.context))),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted
