"""
Golden-file regression test on build_slate() -- the actual selection/
ranking/dedup logic that decides which ~20 of many candidate inferences
become the real slate. Fixed synthetic input + a checked-in expected
output; a silent refactor that changes selection, ordering, or dedup
behavior fails this immediately instead of only showing up as an
unexplained shift in what gets predicted three weeks from now.

Deliberately targets build_slate() rather than the full
generate_for_fixture() pipeline in scripts/generate_slate.py: that
function needs a live Postgres connection with real historical match
data to fit Dixon-Coles/LightGBM against, which isn't reproducible or
offline-runnable the way a golden-file test needs to be. build_slate()
is pure (no DB, no randomness) and is where the actual "which
candidates make the cut" decision lives -- pinning that is the
highest-value part of the pipeline to regression-test this way.
"""
import json
import random
from pathlib import Path

from predictions.generator import Inference, build_slate

GOLDEN_FILE = Path(__file__).parent / "golden" / "slate_expected.json"

MARKETS = ["1X2", "BTTS", "TOTAL_GOALS", "CORNERS", "SOT", "PLAYER_GOALS", "PLAYER_SAVES"]
SIDES = {"1X2": ["home", "draw", "away"], "BTTS": ["yes", "no"]}


def _synthetic_candidates() -> list[Inference]:
    rng = random.Random(42)
    candidates = []
    for i in range(25):
        market = MARKETS[i % len(MARKETS)]
        side = rng.choice(SIDES.get(market, ["over", "under"]))
        team_id = rng.randint(1, 6) if market not in ("PLAYER_GOALS", "PLAYER_SAVES") else None
        player_id = rng.randint(100, 106) if market in ("PLAYER_GOALS", "PLAYER_SAVES") else None
        line = rng.choice([None, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
        probability = round(rng.uniform(0.05, 0.95), 5)
        base_rate = round(rng.uniform(0.2, 0.6), 3)
        candidates.append(Inference(
            market=market, statement=f"synthetic candidate {i}", line=line, side=side,
            probability=probability, subject_team_id=team_id, subject_player_id=player_id,
            base_rate=base_rate))

    # Force the leftover-backfill branch (len(final) < size) to run: a
    # cluster of exact-duplicate keys that all collapse to one kept row,
    # so the primary selection alone can't reach size=20.
    for _ in range(5):
        candidates.append(Inference(
            market="1X2", statement="duplicate-key filler", line=None, side="home",
            probability=0.65, subject_team_id=99, base_rate=0.4))

    return candidates


def _serializable(slate: list[Inference]) -> list[dict]:
    return [{"market": c.market, "statement": c.statement, "line": c.line, "side": c.side,
             "probability": c.probability, "subject_team_id": c.subject_team_id,
             "subject_player_id": c.subject_player_id} for c in slate]


def test_build_slate_matches_golden_file():
    slate = build_slate(_synthetic_candidates())
    actual = _serializable(slate)

    if not GOLDEN_FILE.exists():
        GOLDEN_FILE.parent.mkdir(exist_ok=True)
        GOLDEN_FILE.write_text(json.dumps(actual, indent=2) + "\n")
        raise AssertionError(
            f"No golden file existed -- wrote one to {GOLDEN_FILE}. "
            f"Review it, then re-run; it should pass and be committed.")

    expected = json.loads(GOLDEN_FILE.read_text())
    assert actual == expected, (
        "build_slate() output changed. If this is an intentional behavior "
        f"change, review the diff and regenerate {GOLDEN_FILE.name}; "
        "otherwise this caught a real regression.")


def test_build_slate_exercises_the_leftover_backfill_path():
    """Sanity check on the test data itself: confirms the synthetic
    candidates actually force the len(final) < size backfill branch,
    not just the primary in_band/anchors/specs selection -- otherwise
    the golden file wouldn't cover that code path at all."""
    candidates = _synthetic_candidates()
    lo, hi = 0.60, 0.75
    in_band = [c for c in candidates if lo <= c.probability <= hi]
    anchors = [c for c in candidates if c.probability > 0.80]
    specs = [c for c in candidates if c.probability < 0.45]
    primary_pool_size = min(len(in_band), 15) + min(len(anchors), 3) + min(len(specs), 2)
    assert primary_pool_size < 20, (
        "test data no longer forces the backfill branch -- adjust "
        "_synthetic_candidates() so this golden test still covers it")
