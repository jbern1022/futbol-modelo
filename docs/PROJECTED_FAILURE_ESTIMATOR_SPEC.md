# Projected-failure estimator: technical specification and validation (development)

Todoist `6hm2JMm4XrQJpJcf`. Written 2026-11-02. Code: `src/evaluation/projected_failure.py`
(method `pf-bayesboot-1`). Validation: `scripts/validate_projected_failure.py`.

**Status: development only.** This implements the first method the owner approved on 2026-10-29. It is
**not** a validated estimator. `WARNING_ENABLED` is `False`, nothing in the site, a job or a view calls
it, and two of the four pre-set validation criteria fail (below). Enabling the below-5% warning needs
those results reviewed, the method revised or accepted as is, and the independent statistical review
that ADR-017/ADR-020 require. Projected Failure is a review trigger, never a confirmed failure and
never an automatic replacement.

## What it estimates

For one cohort (league + market + model version, live graded predictions only, time-ordered) and one
fixed decile band: the probability that at N = 1,250 predictions in the band
`|hit rate - mean stated probability| <= 3 points`, given the n results so far.

## Method (the six approved choices)

1. **Target.** Calibration at N = 1,250, tolerance +/-3 points (`TOL_FINAL`). The +/-5-point interim
   benchmark is available through the `tol` argument; the 750-total gate stays in `evidence.py`.
2. **Bands.** Fixed 10-point bands, the same rule as `evidence._band` and the `v_calibration` view
   (`floor(p*10)`, p = 1.0 in band 10), versioned as `deciles-floor-p*10-v1`. The gap compares the
   observed frequency with the **mean stated probability** of the predictions in the band, never the
   band midpoint. Per prediction the quantity is `hit - stated probability`.
3. **Dependence.** Predictions are grouped by `match_id` and resampled as whole matches. The module
   reports a match-clustered standard error of the observed gap. Correlated props are not counted as
   independent. Further dependence across matchweeks is *not yet modelled* (see limits).
4. **Simulation.** Observed results are kept. The remaining `N - n` predictions are simulated: draw a
   "world" as a Bayesian bootstrap over the observed matches (Dirichlet weights, which carries the
   uncertainty about the band's true gap), then draw future matches from that world. Each match brings
   its own stated probabilities, size and hits. *Assumed:* future matches resemble observed ones.
5. **Cadence.** Formal status only at n = 350 and every additional 50 predictions in the band
   (`formal_status`). `sequence_status` replays every checkpoint to expose repeated-monitoring behaviour.
6. **Uncertainty shown.** Each estimate is computed under three assumption variants: `full` (all
   history), `recent` (latest half, at least 350 predictions: drift sensitivity), `diffuse` (full
   history, less certain world, Dirichlet concentration 0.5). Status is `would_warn` if all variants are
   below 5%, `ok` if none are, and **`unstable`** if they disagree. Headline `p_success` is `full`.

Statuses: `insufficient` (n < 350), `ok`, `unstable`, `would_warn`. `warning_active` is always False.

## Validation (pre-set criteria; seed 20261102; 300 series per scenario, 800 simulations per estimate)

Dependence: 5 predictions per match, within-match correlation 0.12 (the props value measured on the
ledger in `PROJECTED_FAILURE_ESTIMATOR_OPTIONS.md`). Stated probabilities uniform on 0.60-0.70.

| Scenario | Series passing at N | Ever would_warn | would_warn at last checkpoint | Ever unstable |
|---|---|---|---|---|
| V1 well-calibrated | 88.7% | 6.7% | 4.3% | 12.7% |
| V2 deteriorating (0 to -10 pts) | 12.3% | 77.7% | 77.0% | 56.0% |
| V3 recovering (-6 pts for 400, then 0) | 76.0% | 35.3% | 14.7% | 49.0% |
| V4 sparse (350 predictions, 14 per match) | 51.7% | 1.3% | 1.3% | 2.0% |

| Criterion (fixed before the first run) | Result |
|---|---|
| V1: among series that pass at N, warned at any checkpoint <= 5% | **meets** (0.8%) |
| V2: deteriorating series warned by n = 1,200 >= 80% | **fails** (77.7%) |
| V3: recovering series warned at the last checkpoint <= 5% | **fails** (14.7%) |
| V4: calibrated sparse series would_warn <= 5% | **meets** (1.3%) |

Reported afterwards, not a gate and not a reason to redefine V2: among V2 series that really fail at N,
88.2% are warned (the headline 77.7% is diluted by the 12.3% that happen to pass).

## What this shows, and what it does not

- Few false alarms on healthy bands (V1) and no alarm from thin data (V4). In V4 the estimator mostly stays
  `ok` rather than `unstable`; a sparse 350-prediction band with only 25 matches should arguably be
  labelled unstable more often, and this is untested beyond the single configuration.
- It is slow to catch a deteriorating band (median first warning near n = 1,000) and misses 12% of the
  V2 series that really fail. It is a late-warning tool, not an early one.
- **Recovery: see the follow-up below.** The first reading here (recovery is handled badly) was
  too strong: it came from V3, whose criterion also counted series that really fail at N. Corrected
  in the follow-up.
- "Below 5%" is not a literal probability under repeated monitoring (see option 5 in
  `PROJECTED_FAILURE_ESTIMATOR_OPTIONS.md`); it remains a review trigger.

## Limits

- Simulation only; one stated-probability band shape, one tolerance, one N. No real ledger data used.
- The world is stationary except through the `recent` variant. Real drift, season boundaries (MLS 2025
  vs 2026) and model-version changes are not modelled; cohorts must still be split by version.
- Dependence across matchweeks: tested in the follow-up (V5); resampling by matchweek made things worse, not better.
- Future fixture counts and probabilities are resampled from the past, not from the actual schedule.
- Negative within-match dependence (1X2, CARDS) is not simulated.
- Not reviewed by anyone. No reviewer has been engaged.

## Follow-up, 2026-11-02 (criteria written into the script before these were run)

Same seed and settings as above; V1-V4 reproduce exactly (300 series, 800 simulations).

**V3b, recovery, the question V3 meant to ask.** Among recovering series that *pass* at N, 0.4% are
warned at the last checkpoint: **meets** (<= 5%). Among those that fail at N, 59.7% are warned, as they
should be. What remains is transient early warnings: 20.2% of recovering series that end up passing
were warned at some earlier checkpoint (median first warning at n = 400), which is the model correctly
reporting a band that was 6 points off for 400 predictions. Whether that is an acceptable review
trigger or noise is a judgement, not a defect the numbers settle. V3 as first written stays in the
table as failing, because that was the criterion.

**Persistence rule (warn only after k consecutive would_warn checkpoints), n = 1,200.**

| Scenario | k | any series | among passing at N | among failing at N |
|---|---|---|---|---|
| V1 well-calibrated | 1 | 6.7% | 0.8% | 52.9% |
| V1 | 2 | 4.0% | 0.0% | 35.3% |
| V1 | 3 | 3.0% | 0.0% | 26.5% |
| V2 deteriorating | 1 | 77.7% | 2.7% | 88.2% |
| V2 | 2 | 68.0% | 0.0% | 77.6% |
| V2 | 3 | 59.3% | 0.0% | 67.7% |
| V3 recovering | 1 | 35.3% | 20.2% | 83.3% |
| V3 | 2 | 25.7% | 13.2% | 65.3% |
| V3 | 3 | 19.0% | 8.3% | 52.8% |

Criterion: k acceptable only if V1 false alarms among passing series <= 5% **and** at least 80% of V2
series that really fail still reach a persistent warning by n = 1,200. **k = 2 fails (77.6%) and k = 3
fails (67.7%)**; k = 1 meets the power bar (88.2%). Persistence does cut transient warnings in the
recovering case (20.2% to 13.2% to 8.3%) but costs more detection than it is worth at this checkpoint
spacing. Note that V1 has no false alarms among passing series at any k, so the false-alarm bar was
never the constraint.

**V5, matchweek dependence** (calibrated on average; each block of 10 matches shares a shift of
sd 4 points):

| Resampling unit | Passing at N | Ever would_warn | Ever warned, given pass | Ever unstable |
|---|---|---|---|---|
| matchweek (`unit_ids`) | 90.3% | 10.7% | **6.3%** | 20.3% |
| match | 90.3% | 7.0% | 1.5% | 14.0% |

Criterion: false alarms among passing series <= 5% when resampling by matchweek: **fails** (6.3%).
Resampling by match, not gated, gave 1.5%. Resampling whole matchweeks leaves only 7 to 8 units at
n = 350 to 400, and a Bayesian bootstrap over so few clusters is anti-conservative: its first warnings
arrive at n = 400, far earlier than the match-level estimator's. With a 4-point shift averaging over
about 25 matchweeks, match-level resampling already stayed inside the line, so this test does not show
a case where matchweek dependence breaks the match-level estimator. It also does not show that it
cannot. `unit_ids` stays available in the code but is not recommended.

**Net.** Eight criteria were written in advance; three meet (V1, V3b, V4) and five fail (V2, V3 as first
written, V5, P2, P3). The headline concern is late detection of a deteriorating band (88.2% power among
truly failing series, median first warning near n = 1,000), and neither persistence nor matchweek
resampling improved it.

## Decisions this leaves to the owner

1. Accept, revise or replace the method given V2 (late detection). Persistence did not help.
2. Whether the V2 criterion should be judged among series that truly fail (88.2%) or all deteriorating
   series (77.7%); it was set on all series, so it is recorded as failing.
3. When to hand the package to independent statistical review (`REVIEW_PACKAGE.md`).
