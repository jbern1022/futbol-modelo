# Projected-failure estimator: candidate methods and how they behave

Todoist `6hm2JMm4XrQJpJcf`. Written 2026-10-29. **This document does not select a method.**
ADR-017 reserves that choice for the owner and requires independent review before the rule runs.
It measures how four candidates behave so the choice can be made on evidence.

## The question, restated for ADR-020

ADR-020 made the 80% goal a *calibration* goal. At N = 1,250 live graded predictions in a
league + market + model-version cohort, each evaluated confidence band should have a realized
rate within the final tolerance (+/-3 points) of its stated probability. From n >= 350 the
projected-failure rule asks: given the n outcomes so far, how likely is that? Below 5% the cohort is
labelled PROJECTED FAILURE (mandatory review; never a deletion, never a confirmed failure).

The simulation fixes one band (stated 0.65), N = 1,250, tolerance +/-3 points, checkpoints every 50
predictions from 350 to 1,200 (the rule is monitored repeatedly), and 4,000 simulated series per cell.

## Why dependence matters (measured, not assumed)

Predictions on the same match are not independent. Within-match intraclass correlation of
`hit - stated probability` on the graded ledger (2026-10-29, read-only):

| Market | within-match ICC | predictions per match |
|---|---|---|
| CORNERS | +0.112 | 5.2 |
| SOT | +0.130 | 5.2 |
| CARDS | -0.179 | 3.4 |
| 1X2 | -0.486 | 2.8 (exactly one of three outcomes hits, so negative by construction) |
| TOTAL_GOALS, BTTS | undefined | 1.0 |

The simulation uses clusters of 5 predictions per match with rho in {0, 0.05, **0.12** (observed for
props), 0.25}. Negative dependence (1X2, CARDS) is **not** simulated; the cluster estimator clips its
design effect at 1, so it would be conservative there rather than exploit it.

## Candidates

| Name | What it does |
|---|---|
| `plugin` | Binomial at the observed rate k/n. Ignores uncertainty in the rate. |
| `betabin` | Beta-binomial, flat prior. Accounts for rate uncertainty; assumes independence. |
| `betabin_c` | Beta-binomial, prior centred on the stated probability, strength 50 predictions. |
| `cluster` | Normal approximation with a cluster-robust design effect estimated from the data. |

## Criteria fixed before the first run

- **C1 (false alarms):** among series whose band *would* pass at N, at most 5% are flagged at any
  checkpoint, at the observed dependence (rho = 0.12).
- **C2 (power):** among series whose true rate is 5 points off, at least 80% are flagged by n = 1,200.
- Reported, not gated: flag precision, median n at flag, behaviour at rho = 0 and 0.25.

## Results (`scripts/experiment_projected_failure_estimators.py`, seed 20261029)

At the observed dependence, **rho = 0.12**:

| Estimator | C1: false flag (calibrated band that would pass) | C2: flagged at a true 5-pt gap | Median n at flag (5-pt gap) |
|---|---|---|---|
| plugin | 15.8%: **fails** | 89.1%: meets | 350 |
| betabin | 6.2%: **fails** | 86.6%: meets | 500 |
| betabin_c | 5.0%: at the line | 86.0%: meets | 550 |
| cluster | 4.0%: **meets** | 84.4%: meets | 600 |

Sensitivity to the dependence assumption (false flag on a calibrated band / flagged by n = 1,200 at a
true 5-point gap):

| rho | plugin | betabin | betabin_c | cluster |
|---|---|---|---|---|
| 0 | 7.4% / 91.4% | 1.9% / 89.3% | 1.4% / 88.9% | 1.9% / 89.3% |
| 0.05 | 11.8% / 89.3% | 3.8% / 86.5% | 2.8% / 86.2% | 3.1% / 85.7% |
| **0.12** | 15.8% / 89.1% | 6.2% / 86.6% | 5.0% / 86.0% | 4.0% / 84.4% |
| 0.25 | 25.3% / 86.6% | 11.4% / 83.0% | 9.7% / 82.3% | **5.1% / 77.9%** |

Full tables (2, 3 and 8-point gaps, flag precision, median n) come from running the script.

## What the numbers say

1. **`plugin` is not acceptable.** It wrongly flags one in six healthy bands at the observed
   dependence, mostly at the first checkpoint (350). It treats a noisy early rate as the truth.
2. **Ignoring dependence is the main error.** Independence-assuming estimators (`betabin`, and to a
   lesser degree `betabin_c`) drift above 5% false alarms as rho rises, because the data are less
   informative than they look. `cluster` is the only candidate that stays near the line at rho = 0.25.
3. **There is a real trade-off.** `cluster` pays for its calm with power: at rho = 0.25 it flags
   77.9% of 5-point-off bands by n = 1,200, below the 80% bar. `betabin_c` keeps power (82.3%) but
   false-alarms 9.7%. No candidate meets both criteria at every rho tested.
4. **Flags arrive late for small gaps.** Excluding `plugin` (which flags at the first checkpoint), a 3-point
   gap has a median flag at n = 600 to 850 and a 5-point gap at 500 to 600.
5. **The "below 5%" figure is not a literal probability under repeated looks.** Among series with
   *no* true gap that get flagged, only 42 to 50% would actually have failed at N (flag precision,
   rho = 0.12). Taking the minimum over 18 checkpoints selects the noisiest moment, so the
   estimator's probability is optimistic about failure. The label PROJECTED FAILURE is therefore a
   review trigger, and ADR-017 already says it is not a confirmed failure; this is the quantitative reason.
6. **Rows with ~0% passing series are not informative for "false flag"** (8-point gap): there are almost
   no passing series to measure.

## Limits of this study

- Simulation only; one band (0.65), one tolerance (+/-3), one N. Interim tolerance (+/-5) and other bands
  were not run.
- The true rate is constant over the 1,250 predictions. Real drift (a model that degrades, or a season
  boundary like the MLS 2025 versus 2026 shift) is not modelled and would make every candidate look better
  than it is.
- Clusters have a fixed size of 5 and a common rho; real matches vary, and the ledger's rho is a single
  pooled estimate from about 440 matches.
- A band's stated probability is treated as one number; real bands mix probabilities within a decile.
- Not tested: requiring the flag to persist for several consecutive checkpoints, a sequential
  (alpha-spending) boundary, or a Bayesian prior fitted from other cohorts. Each addresses point 5 and
  is a reasonable next experiment.

## Decisions this leaves to the owner

1. Which candidate, or a combination (for example `cluster` as the trigger with `betabin_c` as a
   corroborating check)?
2. Whether the false-alarm bar (5%) or the power bar (80%) takes priority when they conflict.
3. Whether to require persistence across checkpoints, and how many.
4. Who does the independent review ADR-017 requires, and on what package
   (`6hWgXxQj4Q9x65c7`).

Nothing here is wired into the site, a job or a view.
