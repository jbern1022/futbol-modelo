# Futbol Modelo — Success Criteria and Stopping Rules

**Status: ACCEPTED — 2026-10-05.**

This document defines the governing project-level success criteria agreed by the project owner. It complements `docs/RESEARCH_PROTOCOL.md`; where older working sample-size or retirement language conflicts with this accepted framework, this document governs and the protocol should be reconciled.

## Research success

Futbol Modelo succeeds when it produces reproducible, immutable and objectively graded forecasts that demonstrate useful predictive skill out of sample. Success requires acceptable calibration and probabilistic scoring, competitive or superior performance against predefined baselines, and stable performance across a meaningful sample. Raw accuracy is reported prominently but never without sample size, calibration and benchmark context.

No single metric may conceal a material failure in another. Targets and evaluation rules are defined before evaluation whenever practical.

## Accuracy objectives

- **League success target:** >=80% raw accuracy within each league.
- **Prop/market ideal/stretch target:** >=80% raw accuracy for each standardized prop/market.
- A league or prop cannot earn the relevant success/stretch designation from accuracy alone: it must also demonstrate positive skill versus its predefined benchmark and retain acceptable calibration/probabilistic scoring.
- Aggregate accuracy is reported but cannot conceal an underperforming league.
- Public accuracy claims always include the denominator and scope: accuracy, N, league, market/prop, model version and evaluation cohort; prop claims also show the frozen benchmark. Standalone claims such as “84% accurate” are prohibited.

## Evidence gates

Each material model lineage is evaluated at common live graded-prediction gates:

| Gate | Meaning |
|---|---|
| **N=350** | First formal evidence/calibration and champion-challenger decision gate |
| **N=750** | Meaningful/Strong Evidence gate |
| **N=1,250** | Mature Evidence gate; required for formal >=80% success/stretch claims |

For confidence-band calibration, 350 live graded observations is the minimum formal evaluation threshold.

A formal evaluation cohort is capped at **three completed seasons**. If a cohort ends below N=1,250:
- N<750 remains insufficient evidence.
- N=750–1,249 may be designated **Strong Evidence**, with actual N and all metrics shown.
- Only N>=1,250 is **Mature Evidence** and eligible for the formal >=80% success/stretch designation.

Historical walk-forward/out-of-sample testing accelerates research decisions but never counts toward the live 1,250 gate and never replaces the separately reported immutable live record.

## Early trajectory and projected failure

Beginning at N>=350, publish:
1. current accuracy;
2. accuracy required over the remaining observations to reach 80% at N=1,250; and
3. the projected probability of ultimately reaching the 80% target.

Use a **Bayesian posterior probability** of the underlying accuracy meeting the 80% target, with the prior documented before use and sensitivity analysis reported. Do not use a simple straight-line extrapolation as the governing projection.

Status rules at N>=350:
- **On Track:** projected probability >=50%.
- **At Risk:** projected probability >=5% and <50%.
- **Projected Failure:** projected probability <5%; mandatory model review.

Anti-flapping rule: after entering At Risk, recovery to On Track requires >=60% projected probability. A Projected Failure designation cannot be erased by a short winning streak; recovery requires documented model review and substantial new evidence or a new model lineage.

Projected Failure is not Confirmed Failure. Catastrophic defects such as leakage, impossible probabilities, pipeline errors or severe systematic defects may trigger intervention before N=350.

## Fixed soccer prediction surface

Every eligible fixture produces the predefined prediction surface; the model may not abstain from difficult markets to inflate accuracy. Genuine upstream-data failures are reported as missing forecasts rather than silently removed.

Required surface:
- 1X2.
- Both teams to score (game-level).
- Game goals: 2+, 3+, 4+, 5+.
- Team goals: 1+, 2+, 3+, 4+ independently for each team.
- Clean-sheet probability for each team.
- Match-total corners: 4+, 6+, 8+, 10+, 12+.
- Team corners: 4+, 6+, 8+, 10+, 12+ independently for each team.
- Saves: 3+, 4+, 5+, 6+, 7+.
- Goalscorers: top five scoring probabilities for each team.
- Assists: top five assist probabilities for each team.

The universal prop accuracy objective remains 80%, subject to benchmark and calibration safeguards.

### Player-event grading

Goalscorer and assist evaluation uses two layers:
- **Top-5 Hit Rate:** intuitive 80% stretch target — whether at least one of the five highest-probability candidates for a team produced the event.
- **Individual probability quality:** every player's probability is separately graded with Brier/log loss and calibration. Top-1, Top-3 and Top-5 hit rates are reported diagnostically.

Preserve each original candidate and later annotate lineup/outcome context: Started, Bench, Not in squad or Unknown; minutes played; scored/assisted; and substitution timing where available.

Report both:
- **Raw Top-5 hit rate**, retaining original predictions including zero-minute players; and
- **Appearance-adjusted Top-5 hit rate**, with exclusions explicit.

The raw result is never hidden or replaced. Morning and lineup-confirmed near-kickoff forecasts are distinct immutable forecast types and are graded separately.

## Voids and rescheduled fixtures

Cancelled, postponed or abandoned fixtures preserve their original predictions but are graded **VOID** and excluded from accuracy, Brier and calibration denominators. Void counts remain public. A rescheduled fixture receives a fresh forecast for its new match time; stale probabilities are never resurrected.

## Benchmarks and concept drift

For each league x prop evaluation lineage:
- Freeze the formal naive/base-rate benchmark from the **previous three completed seasons** where available.
- Record the exact source window and calculation.
- The frozen benchmark remains unchanged through the 350/750/1,250 gates.
- Define and document a fallback before evaluation when three completed seasons are unavailable.
- Maintain a separate rolling current-environment benchmark for concept-drift detection.
- Drift is flagged and investigated; it does not silently rewrite the frozen evaluation standard.

A prop must achieve both >=80% raw accuracy **and** positive skill versus its frozen benchmark to earn success/stretch status.

## Model lineage, retraining and evidence resets

Routine retraining under a frozen methodology **does not reset N**. Updating parameters with newly available data is part of the same model lineage.

A **material methodology change** resets the new model lineage to N=0. Examples include changing the algorithm/model class, feature set, calibration method, objective function, leakage controls, or another methodology decision capable of materially changing model behavior.

Minor fixes that provably cannot change predictions do not create a new evidence lineage.

Previous model histories are never erased. Gate-by-gate comparisons remain visible:
- previous model @350 vs challenger @350;
- @750 vs @750;
- @1,250 vs @1,250.

Preserve forecast dates, competition mix and relevant context so equal-N comparisons are interpretable.

## Champion/challenger governance

The incumbent champion continues producing the official immutable forecast while challengers run in shadow mode where technically possible.

At N>=350 a challenger becomes eligible for promotion only when it:
- meaningfully improves predefined primary metric(s);
- shows no material calibration regression;
- has uncertainty analysis indicating the improvement is unlikely to be random; and
- does not introduce an unacceptable weakness elsewhere.

A challenger that is predictively equivalent may be promoted for a clearly documented material operational advantage such as robustness or data availability.

At N=350:
- clearly inferior with little plausible upside: retire/freeze;
- mixed or uncertain: continue shadow evaluation toward 750;
- clearly superior: eligible for promotion after review;
- catastrophic flaw: terminate immediately.

At N=750, a challenger that still demonstrates neither predictive improvement nor meaningful operational advantage should normally be retired rather than kept alive solely to reach N=1,250.

### League and prop specialization

Champions are allowed to differ by league. A global improvement cannot hide a material league regression.

League x prop specialization is allowed only after the specialized challenger earns its complexity at N>=350 against the shared/current alternative. Specialization is reversible and is re-evaluated at later gates.

## Symmetric public evidence for success and failure

Every promotion **and** retirement receives the same public evidence template. Preserve:
- gate and N;
- accuracy and probabilistic metrics;
- calibration;
- benchmark comparison;
- league/prop breakdown;
- paired champion/challenger results where they saw the same fixtures;
- known improvements and regressions;
- decision and rationale; and
- lessons learned.

Failed challengers remain public research evidence. A retirement record explains where, how much and on which metrics/segments the challenger underperformed. Successful challengers must disclose regressions as well as improvements.

No model transition rewrites the prediction ledger.

## Preregistration and exploratory work

Before the first graded prediction of a confirmatory experiment, preregister:
- hypothesis;
- champion and challenger;
- proposed change;
- primary metric(s);
- affected leagues/props;
- expected direction;
- evaluation gates;
- benchmark; and
- promotion/retirement criteria.

Exploratory analysis is allowed, but findings discovered after inspecting results are labeled **exploratory**. They require confirmation on a new untouched cohort before they may drive promotion. Negative and inconclusive experiments are preserved with the same visibility as positive results.

## Project-level interpretation

Futbol Modelo is a forecasting research platform, not a betting-tip product. Beating betting markets is a useful comparative reference where reliable odds exist, but it is not required for project success.

The benchmark hierarchy is:
1. naive/base-rate benchmark;
2. incumbent production model when testing a replacement;
3. market-implied probabilities where reliable odds data exist.

The project is successful when its live, immutable evidence meets the standards above; it does not redefine success after observing results.

## Related documents

- `docs/RESEARCH_CHARTER.md`
- `docs/RESEARCH_PROTOCOL.md`
- `docs/PLATFORM_CONTRACT.md`
- `docs/EXPERIMENT_REGISTRY.md`
- `docs/DECISIONS.md`
