# Futbol Modelo — Success Criteria and Stopping Rules

**Status: the evidence and success framework below was ACCEPTED on
2026-10-13 (ADR-017, `docs/DECISIONS.md`).** The first strawman that
used to be this document's whole content is kept further down as
history. Where the two conflict, the accepted framework governs. What
the accepted framework does not address stays open, and is listed at the
end of the next section.

> **Amended prospectively by ADR-020 (accepted 2026-10-25, recorded
> 2026-10-29):** the "80% raw accuracy" success targets below are
> superseded. The 80% goal is a *calibration* goal: realized hit rate within
> +/-5 points of stated probability per confidence band, tightening to the
> mandatory +/-3 only when every evaluated band has 1,250+ live graded
> predictions. The 350 / 750 / 1,250 evidence gates are unchanged. The text
> below is kept as written for history.

## Accepted framework (2026-10-13, ADR-017)

Agreed 2026-10-05 (Todoist `6h9M3Ghc9vFXpj6x`), signed off by Joe on
2026-10-13. Live graded predictions only.

**Evidence gates**

| Live graded predictions | What it allows |
|---|---|
| 350+ per confidence band | Minimum for a calibration evaluation |
| 750+ in total | Meaningful model/market evaluation |
| 1,250+ | Mature-evidence threshold for strong performance claims |

**Success targets**

- 80% raw accuracy per league, assessed only once that league has 1,250
  live graded predictions.
- 80% raw accuracy per individual prop/market is the ideal/stretch
  target, also requiring 1,250 for that prop.
- Below 1,250 the status is Insufficient Evidence, not success or
  failure.
- Aggregate accuracy stays visible but cannot hide an underperforming
  league. Calibration, Brier/log loss, benchmark performance and sample
  size remain mandatory context; 80% accuracy cannot mask a material
  failure elsewhere.
- Historical walk-forward or out-of-sample testing may speed research
  decisions but does not count toward the 1,250 live evidence gate and
  never replaces the separately reported, immutable live track record.

**Projected-failure rule**

- From 350 live graded predictions, estimate the probability of
  ultimately reaching 80% at 1,250, and track current accuracy, the
  accuracy still required over the remaining predictions, and that
  projected probability.
- Below 5% at 350 or more: label PROJECTED FAILURE and trigger a
  mandatory model review. This is not a confirmed failure, not a reason
  to delete or overwrite predictions, and is always labelled separately.
- Catastrophic technical or model defects (leakage, impossible
  probabilities, pipeline errors) may trigger intervention before 350.
- A model change creates a new versioned track record; history is never
  rewritten.
- **Not operational yet.** The probability estimator, its assumptions,
  handling of dependent predictions and repeated monitoring, cohort and
  model/market version, and reproducible inputs must be documented and
  independently reviewed first (Todoist `6hm2JMm4XrQJpJcf`). The
  statistical method is not selected.

**Status vocabulary:** Insufficient Evidence → On Track → At Risk →
Projected Failure → mature-evidence success/failure assessment at 1,250.

**Supersedes** the ~100+ high-confidence-band bar as the gate for
calibration claims and the proposed per-sport "validated instance" bar
in the draft below.

**Not addressed by the accepted framework, so still open:** what would
falsify the shared-platform thesis for a sport, sport-level retirement,
and what counts as project completion. The draft text below on those
points is unchanged and remains a proposal, not a decision.

---

# Earlier proposed draft (history; conflicting parts superseded 2026-10-13)

**Original status: PROPOSED — not accepted.** Unlike the other Research
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

## Resolved (2026-09-29)

- **NBA's ADR-009 retirement is an unrelated scope decision, not an
  answer to this document's falsification question.** Confirmed by the
  user: NBA was retired for sourcing/product-coherence reasons —
  basketball would have muddied the original soccer/NFL structural
  contrast — not because the shared ledger/grading architecture needed
  an exception or failed to calibrate after a full graded season (it
  never got that season of dedicated investment to even test). The
  falsification question (see above) stays fully open; nothing about
  it has been answered one way or the other yet.

## What I did not attempt to decide for you

- Whether "project completion" should have a calendar deadline at all,
  independent of the evidence bar above.
- Whether an external/independent statistical review (the still-open
  "Plan independent statistical and reproducibility review" ticket)
  should be a prerequisite for calling any sport "validated," not just
  a nice-to-have.

## Related documents

- `docs/RESEARCH_CHARTER.md` — the thesis this document is trying to
  make falsifiable.
- `docs/RESEARCH_PROTOCOL.md` — the per-model/per-market rules this
  document builds on rather than duplicates.

- `docs/archive/RESEARCH_SUCCESS_CRITERIA_github_2026-10-05.md` — the version published on the public GitHub repository on 2026-10-05, archived verbatim (not reconciled with this document; see its header)
