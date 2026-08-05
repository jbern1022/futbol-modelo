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

from dataclasses import dataclass
from datetime import datetime, timezone

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


def persist_slate(conn, match_id: int, model_version_id: int,
                  slate: list[Inference]) -> int:
    """
    Insert into futbol.predictions. Trigger enforces pre-kickoff lock.

    Uses a bare ON CONFLICT DO NOTHING — no inference clause. The natural key
    is a unique index over COALESCE'd columns (NULL subject/line are normal),
    and an inference clause would have to restate those expressions exactly,
    which silently stops matching the moment the index changes. The bare form
    honours whatever unique indexes exist. prediction_id is a BIGSERIAL, so
    the primary key cannot spuriously absorb a row here.

    Re-running generation against an already-slated match therefore inserts
    only genuinely new rows. Note this holds within a model version: while
    model_versions.version_tag embeds the run date, a re-run on a later day
    mints a new model_version_id and legitimately writes a fresh slate.
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
                     created_at, locked_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (match_id, model_version_id, inf.market, inf.subject_team_id,
                 inf.subject_player_id, inf.statement, inf.line, inf.side,
                 round(inf.probability, 5), now, now),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted
