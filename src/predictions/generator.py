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


def log_degenerate_candidates(cur, match_id: int, candidates: list[Inference],
                              verbose: bool = True) -> list[Inference]:
    """
    predictions.probability has a hard CHECK (0 < probability < 1) -- a
    degenerate model output (e.g. a newly-promoted team with almost no
    fitted history) can round to exactly 0.00000 or 1.00000. build_slate()
    already guards against this reaching persist_slate (see its own
    comment), but did so silently -- a real product question, raised
    twice in Todoist, about whether a drop should be invisible. Records
    each one in degenerate_prediction_skips and returns only the valid
    candidates, so the caller passes that on to build_slate() instead of
    the raw list. Uses the identical 0 < round(p, 5) < 1 condition as
    build_slate()'s own filter -- that filter stays in place as a
    redundant safety net for any other direct caller (e.g. the golden
    slate test), it just never fires for anything routed through here.
    """
    valid, degenerate = [], []
    for c in candidates:
        (valid if 0 < round(c.probability, 5) < 1 else degenerate).append(c)

    for c in degenerate:
        cur.execute(
            """INSERT INTO futbol.degenerate_prediction_skips
                 (match_id, market, statement, side, line, subject_team_id,
                  subject_player_id, raw_probability)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (match_id, c.market, c.statement, c.side, c.line,
             c.subject_team_id, c.subject_player_id, c.probability))
        if verbose:
            print(f"  (dropped degenerate probability: {c.statement} -> {c.probability})")

    return valid


def build_slate(candidates: list[Inference],
                band: tuple[float, float] = TARGET_BAND,
                size: int = SLATE_SIZE) -> list[Inference]:
    # predictions.probability has a hard CHECK (0 < probability < 1),
    # checked against persist_slate's round(probability, 5) -- not the
    # raw float. A degenerate model output (e.g. a newly-promoted team
    # with almost no fitted history) can be small enough to round to
    # exactly 0.00000 (or 1.00000) while still passing a raw 0 < p < 1
    # check, so this must match persist_slate's own rounding or it
    # misses exactly the case it exists to catch. If this candidate
    # reaches persist_slate, the whole fixture's INSERT fails and --
    # since generate_for_fixture has no per-fixture error boundary --
    # takes every other fixture in the same auto_slate run down with
    # it. Filtered once here, at the top, so every downstream bucket
    # (in_band/anchors/specs/leftovers) only ever sees valid candidates.
    candidates = [c for c in candidates if 0 < round(c.probability, 5) < 1]

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
