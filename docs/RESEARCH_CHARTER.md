# Futbol Modelo — Proof-of-Concept Charter

**Status:** Draft — first pass, not yet reviewed by the project owner.

## What this is

Futbol Modelo is primarily an **experimental forecasting platform**,
not a betting-tip product, a generic sports-statistics site, or a
consumer-engagement app. Soccer (MLS/EPL/Serie A/La Liga/World Cup
knockout), NFL, and NBA are the *sports under test*, not separate
products — the point of running more than one sport is to find out
whether a single architecture (one ledger schema, one grading
pipeline, one calibration methodology) can honestly represent,
predict, and evaluate games with fundamentally different structures.

## The central research question

> Can a common, transparent forecasting platform represent, predict,
> and honestly evaluate sports with fundamentally different
> structures — continuous-clock/frequent-scoring (soccer), discrete
> variable-length possessions with a rich scoring vocabulary (NFL), and
> high-scoring/near-continuous possession (NBA) — without special-casing
> each sport into a separate, incomparable system?

Everything else in this charter and the linked research documents
(see below) exists to answer that question honestly, including when
the answer for a given sport is "not yet" or "no."

## Why soccer, NFL, and NBA — not a fourth sport

Soccer and NFL were chosen for their structural contrast (continuous
clock vs. discrete downs, frequent low-variance scoring vs. infrequent
high-variance scoring, draws exist vs. don't). NBA was added as a
third point — near-continuous possession, very high scoring frequency,
almost no draws — see `ADR-009` in `docs/DECISIONS.md` for the
decision record on why the platform's *NBA expansion* work (beyond the
already-shipped `TOTAL_POINTS`/`PLAYER_POINTS` vertical slice) was not
pursued further as of 2026-09-21.

## What "honest" means here, concretely

This project already has one working example of the discipline this
charter is asking every sport to meet: `CLAIMS.md`, which maps every
public claim to one of three states — **Tested**, **Live-verified**,
or **Code path only** — rather than letting "the code exists" quietly
stand in for "this was confirmed." The research documents this charter
introduces (protocol, architecture contract, experiment registry,
data-licensing register, publication rules) extend that same
three-tier honesty discipline from *code claims* to *research claims*:
a model result is not "validated" until it has cleared the bar set in
`docs/RESEARCH_PROTOCOL.md`, and a negative or inconclusive result gets
recorded in `docs/EXPERIMENT_REGISTRY.md` with the same weight as a
positive one.

## What this charter is not

- Not a promise that every sport reaches parity. NFL and NBA are
  explicitly, currently **uncalibrated** (see `CLAIMS.md`) — there is
  not yet enough graded history to fit an isotonic calibrator the way
  soccer's props models do. The charter's success criteria
  (`docs/RESEARCH_SUCCESS_CRITERIA.md`, still pending your sign-off)
  are what will eventually say whether that gap closed, stayed open
  for a defensible reason, or falsified the shared-platform thesis for
  a given sport.
- Not a scope commitment to a fourth sport. See
  `docs/adr/` /`docs/DECISIONS.md` for how sport-scope decisions get
  made and recorded going forward — a new sport is a decision, not a
  default.

## Related documents

- `docs/RESEARCH_PROTOCOL.md` — hypotheses, baselines, evaluation
  windows, calibration standards, retirement rules.
- `docs/PLATFORM_CONTRACT.md` — the shared architecture contract
  (ledger, model registry, grading, calibration views, versioning,
  API surface, track record) and what's sport-specific vs. shared.
- `docs/EXPERIMENT_REGISTRY.md` — the spec every experiment (including
  negative results) gets logged against.
- `docs/DATA_LICENSING.md` — data-source inventory and what each
  provider actually permits.
- `docs/RESEARCH_SUCCESS_CRITERIA.md` — draft, **not yet accepted**;
  needs your review before it governs anything.
- `docs/DECISIONS.md` — ADR-008 (publication/correction rules) and
  ADR-009 (NBA retirement) were added alongside this charter.
