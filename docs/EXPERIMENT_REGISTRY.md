# Futbol Modelo — Experiment Registry

**Status:** Draft spec — not yet reviewed by the project owner. This
file defines the format; entries get added here (or in a linked
per-experiment log) as new experiments run under
`docs/RESEARCH_PROTOCOL.md`.

## Purpose

Same discipline as the prediction ledger, applied to *research*
instead of *predictions*: an experiment's record doesn't get edited
after the fact to look better, and a negative or inconclusive result
is preserved with the same weight as a positive one. This is what lets
`docs/RESEARCH_CHARTER.md`'s central question be answered honestly
instead of by survivorship — if every negative result quietly
disappears, "the platform works" stops meaning anything.

## Required fields per entry

| Field | Description |
|---|---|
| **Date** | When the experiment ran (not when it's written up) |
| **Hypothesis** | What was expected to happen and why, stated before results were seen |
| **Proposed feature/change** | The concrete code/data change under test |
| **Expected effect** | Predicted direction and rough magnitude |
| **Data cutoff** | The as-of date for training data — must respect `docs/RESEARCH_PROTOCOL.md`'s no-shuffling-across-time rule |
| **Evaluation method** | Which baseline (per the protocol's baseline table), which metric, out-of-fold or not |
| **Result** | The actual number(s), not just "better"/"worse" |
| **Limitations** | Sample size, confounds, anything that weakens confidence in the result |
| **Decision: retain / revise / remove** | What actually happened to the change |

## Format

One entry per experiment, appended chronologically — never edited in
place once written (same append-only spirit as `prediction_grades`; a
correction is a new note referencing the original entry, not a silent
edit). A markdown table row per entry is fine for short experiments;
link out to a longer write-up for anything that needs one.

## Already-run experiments worth backfilling into this format

These predate the registry but are real, already-documented
experiments that should be the first entries once this format is
adopted — their write-ups already contain every required field, just
not in this table shape yet:

1. **Referee-tendencies feature for CARDS** (shipped 2026-09-22) — a
   clean, already-registry-shaped A/B: hypothesis (referee data
   predicts CARDS), data cutoff (3899/3900 historical EPL+SERIE_A
   matches, 161 referees), result (-0.4% without the feature,
   reproducing the original finding; +0.1% with it), limitation stated
   explicitly (live predictions fall back to league-average since
   referees aren't known 21-45 days out — the backtest's +0.1% doesn't
   directly prove live calibration), decision: retain, revisit
   `v_calibration` for `market='CARDS'` once graded n is meaningful.
2. **1X2/TOTAL_GOALS calibration generalization** (checked 2026-08-06,
   rechecked 2026-09-02 and 2026-09-21) — the clearest example of an
   honest "not yet" result: direction of miscalibration flipped
   between the 09-02 and 09-21 checks at n=9→18, explicitly called out
   as evidence the sample isn't meaningful, not as a real effect.
   Decision: revisit once each market has 100+ graded predictions in
   the high-confidence band, matching corners/SOT's own bar before
   their fix was validated (ADR-003).
3. **Isotonic calibration for props** (the fix behind ADR-003) — a
   positive result with a documented pre-history: the calibration
   layer existed, tested, and validated in a standalone script for
   *weeks* before being wired into the live `generate_slate.py`
   pipeline. Worth recording as its own registry entry specifically
   because of that gap — it's the concrete example of why
   `docs/PLATFORM_CONTRACT.md`'s methodology-versioning policy
   requires the ADR *and* the registry entry, not just a merged PR.

## Related documents

- `docs/RESEARCH_PROTOCOL.md` — baselines, sample-size bar, and
  evaluation method every entry here is measured against.
- `docs/RESEARCH_CHARTER.md` — why negative results are preserved
  rather than discarded.
