# Futbol Modelo — Research & Evaluation Protocol

**Status:** Accepted research protocol. Project-level evidence gates and success/retirement governance are defined by `docs/RESEARCH_SUCCESS_CRITERIA.md`; where older working thresholds in this protocol conflict, the accepted Success Criteria govern.
Predefining these rules *before* looking at more results is the point;
changing them after seeing how a model performs defeats the purpose
(see "Protections against retrospective metric selection" below).

## Hypotheses under test, per sport

| Sport | Primary hypothesis | Current evidence |
|---|---|---|
| Soccer (MLS/EPL/Serie A/La Liga) | A time-decayed Dixon-Coles model + isotonic-calibrated LightGBM props beats simple baselines and is honestly calibrated | Calibrated and beating baselines for match markets and corners/SOT (see below); 1X2/TOTAL_GOALS calibration still statistically inconclusive per the open ticket "generalize calibration fix beyond corners" (n too small as of 2026-09-21) |
| NFL | Ridge-regression power ratings beat a naive baseline on MONEYLINE/SPREAD/TOTAL_POINTS | Live-verified predictions exist (Week 1 2026); **not yet calibrated** — no graded season history yet |
| NBA | Ridge-regression power ratings + rolling player averages beat a naive baseline on TOTAL_POINTS/PLAYER_POINTS | Live-verified predictions exist; **not yet calibrated**, same reason as NFL |

## Baselines and comparison standards

Every model in this project is compared against the *simplest thing
that could plausibly work* before its added complexity is allowed to
count as validated:

- **Soccer match markets:** league-average outcome rates, then a
  simple Elo variant, then market-implied probability (from
  `match_odds_history`, where available), then the current production
  model. This mirrors `docs/RESEARCH_CHARTER.md`'s honesty framing —
  Dixon-Coles already has a real, tested comparison point in
  `docs/DECISIONS.md`'s ADR-003 (isotonic vs. raw probabilities); this
  section formalizes doing the same against *external* baselines, not
  just against the model's own uncalibrated output.
- **Soccer props (corners, SOT, cards):** a naive per-team rolling
  average with no model at all. The referee-tendencies CARDS feature
  (shipped 2026-09-22, see Todoist) already used exactly this
  discipline — the feature only shipped because it beat that baseline
  in a clean A/B (+0.1% vs. -0.4% without it).
- **NFL/NBA:** the closing/market line where one exists (NFL
  MONEYLINE/SPREAD/TOTAL_POINTS via nflverse's real lines), or a naive
  rolling-average baseline where none exists (NBA has no bookmaker
  data at all — see `docs/DATA_LICENSING.md`).
- **Complexity that doesn't beat its baseline gets published as a
  negative result** in `docs/EXPERIMENT_REGISTRY.md`, not silently
  dropped. The 1X2/TOTAL_GOALS calibration investigation is the first
  real example: the honest conclusion as of 2026-09-21 was "can't be
  answered yet, sample too small" — that conclusion is itself a result
  worth recording, not a placeholder for a future positive one.

## Training/evaluation windows and holdouts

- Time-ordering is never violated: train on seasons strictly before
  the evaluation window, never shuffled across time (this is already
  the discipline `scripts/train_xg_model.py` follows — trained
  2021-22..2024-25, held out 2025-26).
- A model is not evaluated against its own training folds. Where
  out-of-fold evaluation is possible (isotonic calibration already
  requires this — ADR-003), it is mandatory, not optional.
- `tests/test_features_no_leakage.py` is the enforced backstop for
  "rolling features never leak future information into a match's own
  row" — any new feature crossing sports must have an equivalent
  leakage test before it ships, not after.

## Calibration standards

- Calibration remains mandatory and is evaluated by league, market/prop and relevant confidence band.
- The former ~100-observation working precedent is superseded for formal decisions by the accepted evidence gates in `docs/RESEARCH_SUCCESS_CRITERIA.md`: **N=350** is the first formal calibration/evidence gate, **N=750** is Strong/meaningful evidence, and **N=1,250** is Mature Evidence.
- Below N=350, results may be shown descriptively but are not assigned formal On Track / At Risk / Projected Failure status.
- Calibration uses out-of-fold methods where applicable and is never allowed to be masked by raw accuracy.
- NFL/NBA or any market without sufficient graded evidence remains explicitly labeled insufficient/uncalibrated rather than prematurely passed or failed.
- Calibration is checked via `v_calibration` (see `sql/schema.sql`), segmented by market and league.

## Minimum sample sizes

Formal project-level sample-size, cohort and status rules are canonical in `docs/RESEARCH_SUCCESS_CRITERIA.md`. This protocol does not maintain a competing threshold.

## Uncertainty reporting

- Every published probability is either isotonic-calibrated-on-OOF
  (soccer match/props markets meeting the sample bar) or explicitly
  labeled uncalibrated (NFL/NBA today, and any soccer market below the
  sample bar). There is no third, unlabeled state.
- Where a market self-generates its candidate line rather than
  predicting against a real market line (NBA totals/player points,
  NFL player props), that fact is stated alongside the prediction, not
  left implicit — it changes what "confident" can honestly mean when
  there's no external market to have beaten.

## Success/failure thresholds and model-retirement rules

The canonical rules are in `docs/RESEARCH_SUCCESS_CRITERIA.md`:
- >=80% raw accuracy per league is the success target at Mature Evidence (N>=1,250), with calibration/probabilistic quality and benchmark outperformance also required.
- >=80% is the universal prop/market stretch objective, subject to the same safeguards.
- At N>=350, Bayesian projected-success probability drives On Track / At Risk / Projected Failure status; <5% triggers mandatory review.
- Champion/challenger promotion and retirement are gate-based, preregistered where confirmatory, and preserve symmetric public evidence for wins and failures.
- Routine retraining does not reset N; material methodology changes create a new evidence lineage at N=0.
- Model history is never deleted or rewritten.

These accepted rules supersede the earlier two-window/~100-sample retirement heuristic.

## Protections against retrospective metric selection

- This document is versioned in git like any other file: a change to
  a threshold, baseline, or sample-size bar after results exist for
  that market must be a new commit with a clear message, and any
  experiment log entry that used the old standard keeps saying so
  (see `docs/EXPERIMENT_REGISTRY.md`'s own append-only convention).
- Picking the best-looking metric after the fact is exactly what the
  three-tier `CLAIMS.md` discipline (Tested/Live-verified/Code path
  only) and this protocol's fixed sample-size bar exist to block: a
  market either clears the predefined bar on the predefined metric, or
  it doesn't yet.
