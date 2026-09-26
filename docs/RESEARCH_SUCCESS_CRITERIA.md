# Futbol Modelo — Success Criteria and Stopping Rules

**Status: PROPOSED — not accepted.** Unlike the other Research
Foundation documents, this one is a product/direction decision wearing
an engineering-ticket costume, not a documentation task with an
obvious right answer to draft. This is a first strawman for you to
edit or reject — do not treat any threshold below as governing
anything until you've signed off on it.

## Why this one is different

`docs/RESEARCH_PROTOCOL.md` already defines *per-model* retirement
rules (fails its baseline, or miscalibrates for two consecutive
windows). This document is asking a bigger question:
`docs/RESEARCH_CHARTER.md`'s central thesis is "a common platform can
honestly represent, predict, and evaluate structurally different
sports" — at what point would the *evidence* say that thesis is
false, or that the project itself is done, rather than "let's add one
more sport"? That's a call about what this project is *for*, not a
technical threshold I can derive from the code.

## Proposed draft (for your edit, not your rubber stamp)

**What the proof of concept must demonstrate, per sport, to count as a
validated instance of the platform:**
- A model beating its defined baseline (per `docs/RESEARCH_PROTOCOL.md`)
- Calibration confirmed at the ~100+ high-confidence-band sample bar
  (same document)
- At least one full graded season cycle, so the calibration claim
  isn't resting on a partial sample

By this draft bar: **soccer's mature markets (1X2 match outcomes,
corners, SOT) already qualify.** 1X2/TOTAL_GOALS calibration and
NFL/NBA are explicitly not there yet — not failing, just not yet
evaluable (per the protocol's own "not enough data" standard).

**What evidence would invalidate the shared-platform thesis, at least
for a given sport:**
- A sport where the shared architecture (ledger/registry/grading/
  calibration views — `docs/PLATFORM_CONTRACT.md`) turns out to
  require sport-specific exceptions to the *ledger or grading rules
  themselves* (not just a different model class, which is already
  expected and fine — see ADR-001, ADR-009). The model class differing
  per sport was always the plan; the ledger/grading contract *not*
  holding would be the actual falsification signal.
- A sport where, after a full graded season, calibration still cannot
  be achieved even with isotonic-on-OOF fitting — as opposed to simply
  not having enough data yet.

**When an experimental market/model should be retired:** already
covered by `docs/RESEARCH_PROTOCOL.md` — restated here only to note
that a *sport-level* retirement (not just a market) would need enough
retired markets within that sport that the remaining ones can't
support the sport's own presence on the Track Record page.

**What counts as project completion, vs. endless feature expansion —
the part most worth your explicit input:** a draft candidate is
*"soccer, NFL, and NBA (or whatever sports are live at the time) all
reach the validated-instance bar above, or reach an honestly-documented
'why not' via this document's invalidation criteria."* At that point,
further work is explicitly *scope expansion* (a 4th sport, live
in-play predictions, etc.) rather than completing the original POC —
and per `docs/RESEARCH_CHARTER.md`, a new sport should require a
deliberate decision (an ADR), not a default next step. Whether that's
actually the right finish line, or whether it should be something
else entirely (a specific date, a specific external validation, a
specific readership/usage milestone) is genuinely your call.

## What I did not attempt to decide for you

- Whether "project completion" should have a calendar deadline at all,
  independent of the evidence bar above.
- Whether NBA's ADR-009 retirement should be treated as already having
  answered part of this document's "what invalidates the thesis"
  question, or as an unrelated scope decision.
- Whether an external/independent statistical review (the still-open
  "Plan independent statistical and reproducibility review" ticket)
  should be a prerequisite for calling any sport "validated," not just
  a nice-to-have.

## Related documents

- `docs/RESEARCH_CHARTER.md` — the thesis this document is trying to
  make falsifiable.
- `docs/RESEARCH_PROTOCOL.md` — the per-model/per-market rules this
  document builds on rather than duplicates.
