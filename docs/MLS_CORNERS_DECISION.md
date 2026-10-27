# Decision memo: MLS CORNERS (2026-10-27)

Owner decision needed. Context: Todoist `6hmV8gr2VhFrWGh7` (MLS SOT, paused 2026-10-16) and `6hm4XP38mV4gGQ57`
(corners investigation). Evidence is in `docs/EXPERIMENT_REGISTRY.md` ("2026-10-15 Result, an xG-free props model for MLS" and
"2026-10-27 Investigation, corners 70-80% band").

## The defect

`team_match_features.xg_for_r5` is NULL for all 5,810 MLS rows, so `fit_props_model`'s `dropna()` leaves no MLS row in the
CORNERS training set. MLS fixtures are then scored by a model that never saw MLS, with xG missing. SOT showed this clearly
(-16% bias) and was paused. CORNERS shows it less clearly.

## What the numbers say

| | Value |
|---|---|
| Mean-count bias scoring MLS | -7.0% in 2026, -0.9% in 2025 (seasons disagree) |
| Live ledger, MLS corners at stated 0.70+ | overs +0.6 pts (n=83); **unders -8.3 pts, CI [-14.2, -1.9] (n=214)** |
| Other leagues, same band | no cell clearly off |
| Log loss, live model vs xG-free pooled model | 2026: xG-free better by 0.0165 [0.0017, 0.0319]; 2025: **worse** by 0.0125 [0.0009, 0.0247] |

## Options

| Option | Effect | Cost / risk |
|---|---|---|
| **A. Pause MLS CORNERS** (as for SOT) | Stops the one clearly off cell. MLS is about a third of CORNERS rows, so volume drops. | Needs a code change (`PROPS_MARKETS["CORNERS"]["leagues"]` minus MLS) and a deploy, plus voiding the upcoming MLS CORNERS rows (like `void_mls_sot.py`). No new modelling. |
| **B. Accept an xG-free model for MLS** | Removes the "xG missing at predict time" mismatch. Registry: passes calibration in 2026, fails the registered R1 skill rule (the 2025 holdout has the opposite sign) and R4 bias by 0.1 pt. | Needs an ADR and a model-version bump. Evidence is mixed, and the registry did not recommend it. |
| **C. Pre-register a trailing league-offset variant** | Addresses level shifts between seasons (seen in SOT). | A new pre-registration and experiment; no live fix for weeks. Likely the right long-term answer. |
| **D. Do nothing** | Keeps publishing MLS corners with an unders cell about 8 pts over-confident. | Honest only if the track-record page says so. Evidence is one 9-week stretch, and the gap narrowed over time. |

## Recommendation

A now, C afterwards. The defect is real and mechanically explained, A is the smallest reversible change, and it matches
how SOT was handled. B's registered rule says "not recommended". D is defensible only if you prefer more data first: the latest
three weeks of the whole corners band show -2.3 pts [-7.2, +3.1], so the case is weaker than it looked at n=246.
Choosing between A and D is the owner's call; this memo does not authorize either.
