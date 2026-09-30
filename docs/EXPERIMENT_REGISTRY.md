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

## Entries

First entry actually logged in this format (everything above is
spec/backfill-list only).

### 2026-09-29: absence_rate_r10 for PLAYER_GOALS / PLAYER_SAVES

| Field | PLAYER_GOALS | PLAYER_SAVES |
|---|---|---|
| **Hypothesis** | A trailing per-player absence/rotation rate (`player_injury_features.absence_rate_r10`) improves player-prop predictions, same structural fix as CARDS' `referee_avg_cards_r10`. | Same hypothesis, applied to goalkeeper saves. |
| **Proposed change** | Add `absence_rate_r10` to `fit_player_goals_model()`'s feature list. | Add `absence_rate_r10` to `fit_player_saves_model()`'s feature list. |
| **Expected effect** | Small positive — same order of magnitude as CARDS' referee feature (+0.1%). | Same, small positive expected. |
| **Data cutoff** | MLS only (full injuries backfill this session covered MLS 2026 season; other leagues/seasons not yet backfilled). Train: 2021-2025 seasons. Test: held-out 2026 season. | Same. |
| **Evaluation method** | Season-holdout Poisson log-loss vs. the current live feature set (not vs. a naive baseline — both variants already beat naive), `scripts/train_props_player_goals.py`. | Same method, `scripts/train_props_saves.py`. |
| **Result** | WITHOUT: log-loss 0.4227 (n=6392 test rows). WITH: log-loss 0.4213 (n=6360). **+0.33% improvement.** | WITHOUT: log-loss 2.0152 (n=745). WITH: log-loss 2.0175 (n=737). **-0.12% regression.** |
| **Limitations** | Same live-timing gap as CARDS: `absence_rate_r10` is a real per-player prior, but the *actual* confirmed lineup is rarely known at original slate-generation time — see ADR-010's final pass for the partial fix. MLS-only backtest; not yet validated for EPL/SERIE_A/LA_LIGA. | Goalkeeper sample is ~9x smaller than outfield players (737 vs 6360 held-out rows) — may be genuine noise rather than a real negative effect, same "not enough data to tell" caveat as the open 1X2/TOTAL_GOALS calibration question. |
| **Decision** | **Retain.** Wired into the live `fit_player_goals_model()`. | **Remove (don't ship).** `fit_player_saves_model()` deliberately excludes it — doesn't clear the beat-baseline bar this session's data supports. Revisit once goalkeeper sample size grows or once EPL/SERIE_A/LA_LIGA injuries backfill exists. |

### 2026-09-29: Elo vs. Dixon-Coles for 1X2 (Phase 1 of Todoist `6hf55hCCX78Wc6m7`)

| Field | Detail |
|---|---|
| **Hypothesis** | An independent outcome-rating signal (Elo) can match or beat Dixon-Coles' 1X2 probabilities standalone, or reveal complementary errors worth blending. |
| **Proposed change** | Standalone Elo model: match-by-match rating updates (home advantage +100, standard published value, not tuned), pre-match `elo_diff` mapped to 1X2 via multinomial logistic regression. |
| **Expected effect** | Unknown going in — genuinely exploratory, not assumed to add independent signal (per the ticket's own framing). |
| **Data cutoff** | 2025-26 holdout season (2026 for MLS); trained on all seasons strictly before, weekly walk-forward refit — same harness `scripts/train_dixon_coles.py` already uses, for a fair comparison. |
| **Evaluation method** | RPS (primary) and log-loss (secondary), paired per-league, `scripts/experiment_elo_vs_dixon_coles.py`. |
| **Result** | EPL: DC wins both (RPS 0.2078 vs 0.2100). SERIE_A: DC wins RPS (0.1995 vs 0.2036), Elo wins log-loss. LA_LIGA: DC wins RPS narrowly (0.2014 vs 0.2019), Elo wins log-loss. **MLS: Elo wins BOTH (RPS 0.2209 vs 0.2269, log-loss 1.0506 vs 1.0679).** |
| **Limitations** | Single scalar feature (elo_diff) — a deliberately simple baseline, not a tuned Elo variant. Home-advantage constant (100) is a standard published value, not fit to this data. One holdout season per league — not yet checked for stability across multiple seasons. |
| **Decision** | **Remove (as a standalone replacement) for EPL/SERIE_A/LA_LIGA** — Dixon-Coles stays. MLS result below. |

### 2026-09-29: 1X2 blend (Dixon-Coles + Elo) for MLS — Phase 1 step 2

| Field | Detail |
|---|---|
| **Hypothesis** | Phase 1's MLS result (Elo beats DC on both RPS and log-loss, 2026 holdout) is a real, complementary signal worth a small fixed blend, not noise. |
| **Proposed change** | `p_blend = alpha * p_dixon_coles + (1-alpha) * p_elo`, alpha swept 0.0-1.0 in steps of 0.1. |
| **Expected effect** | A blend RPS beating both single models on a genuinely untouched season. |
| **Data cutoff** | Alpha selected ONLY on the 2025 validation season (532 matches); scored on the 2026 test season (402 matches), completely untouched during alpha selection — per this ticket's own explicit methodology requirement. `scripts/experiment_blend_1x2_mls.py`. |
| **Evaluation method** | RPS on the held-out 2026 season, alpha chosen by minimum RPS on the separate 2025 validation season. |
| **Result** | **Validation (2025): alpha=1.0 (pure Dixon-Coles) was BEST** — RPS monotonically improved from 0.2248 (pure Elo) to 0.2205 (pure DC) as alpha increased. This is the OPPOSITE of Phase 1's finding on the 2026 test season (pure Elo RPS 0.2209 vs pure DC 0.2269). The selected blend (alpha=1.0, i.e. pure DC) scores 0.2269 on test — identical to plain Dixon-Coles, worse than plain Elo (0.2209). |
| **Limitations** | Only two MLS seasons compared (2025 vs 2026) — a direction flip on n=2 is not enough to call either season's result noise with confidence, same honest limitation as the open 1X2/TOTAL_GOALS calibration question elsewhere in this doc. Real, not hypothetical: this is the exact failure mode walk-forward validation-then-test is supposed to catch, and it did. |
| **Decision** | **Do not promote.** Phase 1's MLS signal did not survive out-of-sample validation on a different season — textbook direction-instability, the same signature that already correctly held back the 1X2/TOTAL_GOALS calibration fix elsewhere in this project. Steps 3-4 of the parent ticket (score-matrix residual diagnosis, bivariate Poisson) are **not started** — their own trigger ("if persistent") is now unmet for MLS too, same as it already was for EPL/SERIE_A/LA_LIGA. Revisit if a 3rd MLS season's result is available to break the tie, not before. |

### 2026-09-30: In-play win-probability via conditioned Dixon-Coles (Todoist `6h9M3GgfQ5ch7wXQ`, Phase 3)

| Field | Detail |
|---|---|
| **Hypothesis** | A live win-probability can reuse Dixon-Coles' already-fitted per-team goal rates (λ, μ, ρ), re-derived for remaining time and conditioned on the current score — no new model class needed, contrary to this ticket's own original framing. |
| **Proposed change** | `inplay_probs()` in `scripts/experiment_inplay_dixon_coles.py`: scale λ/μ by `(90-minute)/90`, build a small additional-goals scoreline matrix, combine with the current score. Offline validation only — no live polling, no new tables, no UI, per explicit direction. |
| **Expected effect** | In-play RPS should beat the static pre-match probability, improving as more of the match elapses. |
| **Data cutoff** | 2025-26 holdout season, EPL/SERIE_A/LA_LIGA (MLS has no goal-minute data — `futbol.shots` is Understat-sourced only). Real historical goal-minute data (`futbol.shots`, `result='Goal'`) used as an offline proxy for live score trajectories at 5 checkpoints (15/30/45/60/75 min). |
| **Evaluation method** | Paired RPS and log-loss vs. the static (unconditioned) pre-match probability, per checkpoint minute. |
| **Result** | EPL: beats static at every checkpoint, +48.8% RPS by minute 75. SERIE_A: beats static at every checkpoint, +58.4% RPS by minute 75. **LA_LIGA: RPS improves (+35.7%) but log-loss WORSENS (0.9872 → 1.2139 at minute 75)** — opposite pattern, some confidently-wrong calls. |
| **Limitations** | La Liga's `shots` coverage is much thinner (380/1973 matches have any rows, vs ~1900/1950 for EPL/SERIE_A) — anomaly may be a thin-data artifact, not investigated further yet. MLS entirely unvalidated (no data). Dixon-Coles' low-score correction (ρ) applied to a shortened remaining-time window is an untested approximation. No red-card/major-incident adjustment. |
| **Decision** | **Promising, not yet promoted — real open questions remain** (La Liga anomaly, MLS data gap, ρ approximation, no live infra built). Full list in Todoist `6h9M3GgfQ5ch7wXQ`. Next step (live backend scoping) is a product decision, not yet made. |

## Related documents

- `docs/RESEARCH_PROTOCOL.md` — baselines, sample-size bar, and
  evaluation method every entry here is measured against.
- `docs/RESEARCH_CHARTER.md` — why negative results are preserved
  rather than discarded.
