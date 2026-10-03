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
| **Result** | EPL: beats static at every checkpoint, +48.8% RPS by minute 75. SERIE_A: beats static at every checkpoint, +58.4% RPS by minute 75. LA_LIGA (initial run): RPS improved (+35.7%) but log-loss WORSENED (0.9872 → 1.2139) — traced to a real data bug (see below), **re-run after the fix: beats static on BOTH metrics at every checkpoint, +49.4% RPS by minute 75, no more anomaly.** |
| **Limitations** | La Liga's `futbol.shots` table only has data for the 2025-26 season (2021-22 through 2024-25 never backfilled) — the in-play validation above is real but single-season for that league, not yet checked across multiple seasons like EPL/SERIE_A implicitly are via the same holdout methodology. ρ ablation (below) shows the low-score correction barely matters — dropped. |
| **Decision** | **Real, validated result for all 4 leagues.** The La Liga anomaly was NOT a modeling problem — root-caused to a real bug in `shots_natural_key`'s unique constraint (NULL `situation` never dedupes in Postgres), which let 1365 duplicate goal rows land, 100% in La Liga. Fixed (`sql/migrations/0037_fix_shots_null_situation_dedup.sql`); re-validated clean. ρ (Dixon-Coles' low-score correction) tested with an ablation — negligible effect (4th decimal place), dropped from the in-play calculation. MLS validated 2026-09-30 after building `match_events` (see entry below) — +43.8% RPS by minute 75, same clean pattern. Red-card multiplier calibrated and wired in separately (see its own entry above). Live rollout stays gradual per product decision (EPL/SERIE_A deployed; MLS/LA_LIGA validated but not yet added to the live poller) — tracked in Todoist `6h9M3GgfQ5ch7wXQ`. |

### 2026-09-30: `match_events` — MLS goal-minute source (unblocks MLS in-play validation)

| Field | Detail |
|---|---|
| **Hypothesis** | API-Football's `/fixtures/events` can substitute for Understat's `shots` table (zero MLS coverage) as a real, minute-precise goal-event source for MLS. |
| **Proposed change** | New `match_events` table (`sql/migrations/0039_match_events.sql`) + `fetch_and_store_events()`/`normalize_events()` (`src/ingestion/api_football.py`) + `scripts/backfill_match_events.py`. |
| **Expected effect** | Real goal-minute coverage good enough to run the same in-play backtest already validated for EPL/SERIE_A/LA_LIGA. |
| **Data cutoff** | MLS 2026 season only (402 finished matches, bounded backfill — same scope discipline as the injuries backfill). |
| **Evaluation method** | Confirmed against a known real fixture (Columbus Crew vs. Inter Miami, 1490510) before the full backfill; then the same `scripts/experiment_inplay_dixon_coles.py` checkpoint methodology used for the other 3 leagues. |
| **Result** | 402/402 fixtures backfilled cleanly, 6,666 events stored, 0 skipped. Found and handled a real gotcha before it could bite: `type='Goal'` events include `detail='Missed Penalty'` (not an actual goal) and `detail='Own Goal'` (team attribution not yet confirmed) — both excluded, only `'Normal Goal'`/`'Penalty'` counted, same conservative stance the `shots`-based query already takes for own goals. Also proactively applied the `shots_natural_key` NULL-dedup lesson (migration 0037) to `match_events`' own unique index before it could repeat the same bug. |
| **Limitations** | Single season (2026) only — not yet checked across multiple MLS seasons the way EPL/SERIE_A's validation implicitly spans several via one holdout split. `Own Goal` events aren't counted at all (rare undercount, same call made for `shots`). |
| **Decision** | **Retain.** MLS now has a real goal-minute source; the in-play model validates cleanly (+43.8% RPS at minute 75). Not yet added to the live `futbol-live-winprob` rollout — that's the same gradual-expansion product decision as La Liga, not a technical blocker. |

### 2026-09-30: Red-card remaining-time scoring multiplier (ADR-011 follow-up)

| Field | Detail |
|---|---|
| **Hypothesis** | A team reduced to 10 men scores fewer remaining goals than Dixon-Coles' unadjusted expectation; their opponent scores more. |
| **Proposed change** | Empirical `(down_factor, up_factor)` multiplying the sent-off team's/opponent's remaining-time λ or μ, derived from real historical data rather than a published literature guess. |
| **Expected effect** | down_factor < 1, up_factor > 1, both leagues showing the same direction. |
| **Data cutoff** | All EPL/SERIE_A seasons 2021-22 through 2026-27 with a recorded red card (`team_match_stats.reds >= 1`), single-red-card matches only, card between minute 10-80. Real red-card minute + team from `/fixtures/events` (backfilled fresh — required first fixing a separate historical-fixture-lookup limitation, Todoist `6hfxhQccV87r4jcx`). Real remaining-time goals from `futbol.shots`. `scripts/experiment_redcard_calibration.py`. |
| **Evaluation method** | `SUM(actual remaining goals) / SUM(Dixon-Coles-expected remaining goals)`, aggregated across all usable matches (not a per-match average, to avoid instability from small per-match denominators). In-sample RPS check: apply the derived factor to the same matches' in-play probability, compare against unadjusted. |
| **Result** | EPL (145 usable matches): down_factor 0.475, up_factor 1.551. In-sample RPS: 0.1435 → 0.1200 (+16.4%). SERIE_A (149 usable matches): down_factor 0.584, up_factor 1.850. In-sample RPS: 0.1595 → 0.1111 (+30.3%). Same direction both leagues, magnitudes differ (possibly real, possibly ~150-match sample noise — not yet distinguished). |
| **Limitations** | In-sample only — factors were derived from the same matches used to check whether they help, not a held-out set. Neither league currently has enough red-card matches to split into calibration/validation halves the way the Elo blend experiment did. Single-red-card, minute 10-80 only (multi-card and very-early/late-card matches excluded). Own goals excluded from the goal count (rare, risk of misattribution). No MLS/LA_LIGA calibration yet. |
| **Decision** | **Wired into production** (`src/predictions/live_winprob.py`'s `RED_CARD_FACTORS`, `apply_red_card()`) — direction is strong and consistent across both leagues, and the in-sample effect size is large enough that shipping it is better than the previous 1.0 no-op stub, with the in-sample-only caveat stated plainly in the code. Revisit with an out-of-sample check once more red-card matches accumulate (more seasons, or MLS/LA_LIGA added). |

### 2026-10-02: In-play stoppage time — empirical remaining-goal share (ADR-013)

| Field | Detail |
|---|---|
| **Hypothesis** | The in-play model's remaining-time rule, `max(90 - minute, 1) / 90`, undercounts late goals. API-Football's `status.elapsed` caps at 90 through stoppage, so all of stoppage counts as 1 minute. Found checking real live series (MLS match 4606: 1-1 in stoppage at draw 0.966, then a home winner). Across 4,180 EPL/SERIE_A/LA_LIGA matches, 0.197 goals per match come at minute ≥ 90 (18.4% of matches have one). |
| **Proposed change** | Replace the linear rule with the empirical share of goals scored after each elapsed minute (0–90), pooled from EPL + SERIE_A Understat goals. |
| **Expected effect** | Better late-match log loss/RPS. Roughly neutral early, since the two rules only diverge by stoppage time. |
| **Data cutoff** | Holdout 2025-26 per league. Evaluation curve: EPL + SERIE_A goals from 2021-22 to 2024-25 only (no holdout leakage). La Liga has shots for 2025-26 only, so its run is an out-of-league test of a curve it never contributed to. MLS holdout 2025 via `match_events`. Production curve refit on all 10,160 EPL + SERIE_A goals after evaluation. `scripts/experiment_inplay_stoppage.py`. |
| **Evaluation method** | Paired RPS and log loss, linear vs. empirical, on the same fitted Dixon-Coles rates, at checkpoints 15/30/45/60/75/80/85/88/89/90 (ADR-011's validation stopped at 75). |
| **Result** | Empirical wins every checkpoint from 75' on, in all three Understat leagues. Log loss at 89': EPL 0.758 → 0.513 (377 matches), SERIE_A 0.492 → 0.352 (341), LA_LIGA 0.476 → 0.341 (335, out-of-league). Before 60': within ±0.001 (EPL/SERIE_A); slightly better throughout for LA_LIGA. **MLS (corrected 2026-10-02):** the first run scored 33 "usable" matches that were all goalless games with no event data (MLS 2025 had no `match_events` yet; the script only skipped matches that had goals but no goal rows). After backfilling 2025 events (533 fixtures, 8,752 events) and requiring data coverage: 532 matches, empirical wins from 75' on, 89' log loss 0.611 → 0.423. |
| **Limitations** | Understat and API-Football minute conventions for stoppage are taken as-is. Own goals excluded (same call as every other in-play query). |
| **Decision** | **Adopted for EPL/SERIE_A/LA_LIGA**, and **MLS too after the corrected run** (`REMAINING_GOAL_SHARE`, `remaining_share()` in `src/predictions/live_winprob.py`). **Red-card factors recalibrated against the new rule**, because the old ones had absorbed the stoppage-goal gap: EPL (0.475, 1.551) → (0.419, 1.370), in-sample RPS +16.0%; SERIE_A (0.584, 1.850) → (0.513, 1.629), +29.3%. Same 145/149 matches. |

### 2026-10-02: Dynamic (score-driven) attack/defence ratings vs. Dixon-Coles (Todoist `6hf54hvcpV9p7Vff`)

| Field | Detail |
|---|---|
| **Hypothesis** | Ratings updated after every match would track form changes faster than a weekly Dixon-Coles refit with time decay, and improve 1X2. |
| **Proposed change** | Same parametrization as Dixon-Coles. Start each season from a DC fit (shrunk toward average by `shrink`), then after each match `atk_h, dfn_a += eta*(hg - lam)` and `atk_a, dfn_h += eta*(ag - mu)`. |
| **Expected effect** | Lower RPS, especially early and mid season. |
| **Data cutoff** | `eta` ∈ {0.01..0.08} and `shrink` ∈ {1.0, 0.8, 0.6} tuned on 2024-25 (MLS 2024); holdout 2025-26 (MLS 2025) scored once. `scripts/experiment_dynamic_ratings.py`. |
| **Evaluation method** | Paired against production-settings DC (xi=0.0015, weekly refit) on matches both price; bootstrap 95% CIs on RPS and log loss. |
| **Result** | RPS diff (dynamic − DC): EPL −0.0003 [−0.0066, +0.0052], SERIE_A −0.0007 [−0.0040, +0.0023], LA_LIGA −0.0012 [−0.0047, +0.0019], MLS −0.0004 [−0.0051, +0.0045]. Same direction in all four, none significant. The apparent log-loss win (EPL 1.062 → 1.031, LA_LIGA 1.014 → 0.980) is one match each where DC scored log loss 14.9 / 13.8. That's a DC bug, not a dynamic-ratings edge (see the next entry). |
| **Limitations** | One holdout season per league. The update ignores xG and match importance. |
| **Decision** | **Not promoted.** Honest negative result. Revisit only as part of the staged feature-integration task. |

### 2026-10-02: Ridge penalty for full-league Dixon-Coles (ADR-014)

| Field | Detail |
|---|---|
| **Hypothesis** | With `reg=0`, a team with zero goals scored (or conceded) in its fit window has an unbounded MLE rating, producing near-zero probabilities. Seen live: promoted Coventry priced at 5e-8 to win (`degenerate_prediction_skips`, Sep 2026). |
| **Proposed change** | `reg` 0 → 0.25 for full leagues (`src/models/dc_settings.py`). |
| **Expected effect** | Bounded tails, with no cost on normal matches. |
| **Data cutoff** | Tune 2024-25 (MLS 2024): reg ∈ {0, 0.25, 1, 4}. That season had **no blowups in any league** (worst log loss ≤ 2.98), so tuning by mean log loss picked reg=0 for three leagues. A rare failure can't be tuned on a season that doesn't contain it. So the candidate was fixed in advance as the smallest reg with no tune-season cost (log loss +0.0003 / 0.0000 / +0.0001 / −0.0023), then the 2025-26 holdout was scored once. `scripts/experiment_dc_ridge.py --fixed-reg 0.25`. |
| **Evaluation method** | Paired weekly walk-forward vs. reg=0, bootstrap 95% CIs, plus worst-case log loss and lowest stated probability. |
| **Result** | Lowest stated probability: EPL 3.4e-7 → 0.036, LA_LIGA 3.3e-7 → 0.030, MLS 6.5e-7 → 0.029 (SERIE_A already 0.042). Worst log loss: EPL 14.90 → 3.32, LA_LIGA 13.81 → 2.53. RPS: −0.0004, −0.0005, −0.0002, −0.0001 (no cost, slight gain). Mean log loss: EPL −0.031, LA_LIGA −0.031 (CIs just touch 0, because the gain comes from single matches). |
| **Limitations** | Blowups are rare (one per league-season here), so mean-metric CIs are wide by nature. The case for the fix is the bounded worst case, which is unambiguous. |
| **Decision** | **Adopted** (slate generator, final pass, live poller and team ratings, via one shared setting). Soccer slate model version → `v3`. |

### 2026-10-03: MLS red-card multiplier, out-of-sample (ADR-011 follow-up)

| Field | Detail |
|---|---|
| **Hypothesis** | MLS shows the same 10-men effect as EPL/SERIE_A (fewer remaining goals for the sent-off team, more for its opponent). |
| **Proposed change** | `RED_CARD_FACTORS["MLS"]`, from `match_events` (red-card minute/team and goals). No API calls. |
| **Expected effect** | down < 1, up > 1; better in-play RPS after a red card. |
| **Data cutoff** | MLS 2025 + 2026, single red card, minute 10–80 (42 + 37 matches). 2025 events backfilled 2026-10-02. `scripts/experiment_redcard_calibration_mls.py`. |
| **Evaluation method** | **Out-of-sample**, which the EPL/SERIE_A factors never had: calibrate on one season, score in-play RPS at the red-card minute on the other (adjusted vs. unadjusted), both directions, then pool the 79 out-of-sample predictions with a bootstrap 95% CI. Same remaining-time rule as live (`remaining_share`, empirical for MLS). |
| **Result** | 2025 factors (0.401, 1.420) → 2026 RPS +19.9%; 2026 factors (0.601, 1.759) → 2025 RPS +20.8%. Pooled: RPS 0.1690 → 0.1346 (+20.4%), diff −0.0344, 95% CI [−0.0644, −0.0049]. |
| **Limitations** | 79 matches, under the ~100 bar; per-season factors differ (0.40 vs 0.60 down). Dixon-Coles rates come from the production fit, which includes these seasons' results (same as the EPL/SERIE_A calibration). |
| **Decision** | **Shipped pooled factors (0.488, 1.579).** The out-of-sample gain is significant and replicates in both directions. LA_LIGA remains the only uncalibrated league. |

### 2026-10-03: API-Football expected_goals as the current-season xG source

| Field | Detail |
|---|---|
| **Hypothesis** | API-Football's `expected_goals` can stand in for Understat xG, which stopped at 2025-26 (a one-off historical load; the nightly refresh only pulls API-Football). Every 2026-27 `team_match_stats.xg` was NULL, so the CORNERS/SOT models' `xg_for_r5`/`xg_against_r5` went down LightGBM's missing-value branch for EPL/SERIE_A/LA_LIGA all season. That branch was learned from MLS rows, which never had xG. |
| **Proposed change** | Parse `expected_goals` in the existing `/fixtures/statistics` calls, rescale to Understat's scale, and fill `xg` only where NULL, for EPL/SERIE_A/LA_LIGA only. Keep the raw value in `team_match_stats_by_source` (migration 0040). |
| **Expected effect** | Current-season props features match what the models were trained on. |
| **Data cutoff** | 2025-26, 100 random matches (200 team-matches) per league with both sources. `scripts/experiment_api_football_xg.py`. |
| **Evaluation method** | Correlation, mean bias and a linear fit, API-Football vs. Understat on the same team-matches. |
| **Result** | Correlation EPL 0.915, SERIE_A 0.913, LA_LIGA 0.901. API-Football runs ~10% lower (slopes 0.77–0.83, mean abs diff 0.24–0.26). Pooled mean ratio Understat/API-Football = 1.108. |
| **Limitations** | A linear rescale doesn't make the providers identical (r ≈ 0.91). The rolling 5-game features average much of the per-match difference away. Not yet measured on props-model accuracy directly. |
| **Decision** | **Adopted** (`store_api_football_xg`, scale 1.108). Backfilled all 2026-27 EPL/SERIE_A/LA_LIGA matches (338 team-matches) on 2026-10-03; the nightly refresh fills new matches. MLS stays xG-less, matching its training data. |

### 2026-10-03: Goals + xG blend in the Dixon-Coles 1X2 fit (Todoist `6hf57MFQwFpGmp57`)

| Field | Detail |
|---|---|
| **Hypothesis** | Team ratings fit partly to xG (less noisy than goals) improve 1X2. |
| **Proposed change** | A second set of ratings fit to Understat xG (quasi-Poisson, same parametrization and production weighting: xi=0.0015, reg=0.25), blended on the log-rate scale: `log rate = (1-w) log rate_goals + w log rate_xg`, with the goals model's rho. |
| **Expected effect** | Lower RPS, mostly early season. |
| **Data cutoff** | EPL and SERIE_A (the only leagues with Understat xG for every season). **Rolling origin**: w ∈ {0, .25, .5, .75, 1} tuned on season k−1, scored once on season k, for k = 2023-24, 2024-25, 2025-26. `scripts/experiment_xg_blend.py`. |
| **Evaluation method** | Paired weekly walk-forward vs. goals-only (w=0); per-match differences pooled across the six holdouts; bootstrap 95% CIs. |
| **Result** | Tuned w per holdout: EPL 1.0 / 0.5 / 1.0, SERIE_A 0.0 / 0.75 / 0.75. RPS diffs: EPL +0.0006 / −0.0017 / −0.0026, SERIE_A 0 / −0.0018 / +0.0001. **Pooled (n=2,272): RPS 0.1980 → 0.1971, diff −0.0009, 95% CI [−0.0024, +0.0005]; log loss −0.0017 [−0.0067, +0.0030].** Not significant. Tuning on one prior season is noisy and keeps landing on extreme weights (w=1.0 hurt EPL 2023-24). Observed, but **not usable as evidence** because it was read off the holdouts: a fixed w=0.5 scored at or below goals-only RPS in all six holdouts. |
| **Limitations** | Two leagues, three seasons each. Choosing w=0.5 now would be selection on the test data. |
| **Decision** | **Not promoted.** Pre-registered follow-up: evaluate a fixed w=0.5 blend prospectively on 2026-27 EPL/SERIE_A once ~150+ matches have been played. Fixed before seeing any of that season's results; compute it from the same script with w pinned. |
| **Pre-registration, La Liga (2026-10-03, committed before running)** | La Liga's 2021-25 Understat xG was backfilled today (ADR-015), and none of it was used to pick w=0.5. So it's a second untouched test of the same fixed blend. Test: `--league LA_LIGA --fixed-w 0.5`, holdouts 2022-23, 2023-24, 2024-25, 2025-26 (weekly walk-forward, each fit only on earlier seasons). Pool the per-match RPS differences vs. goals-only, bootstrap 95% CI. **Success = CI entirely below 0.** Anything else is a fail and gets recorded as one. |
| **La Liga result (2026-10-03)** | **Passed.** RPS goals-only → blend: 2022-23 0.2122 → 0.2068, 2023-24 0.1871 → 0.1851, 2024-25 0.1957 → 0.1939, 2025-26 0.2008 → 0.1999. Pooled n=1,514: diff −0.0026, 95% CI [−0.0037, −0.0014]; log loss −0.0088 [−0.0130, −0.0049]. **Promoted** for EPL/SERIE_A/LA_LIGA (ADR-016). The EPL/SERIE_A prospective 2026-27 test stays scheduled; it's the first check on API-Football-sourced current-season xG. |

### 2026-10-03: La Liga red-card multiplier

| Field | Detail |
|---|---|
| **Hypothesis** | Same 10-men effect as the other three leagues. |
| **Proposed change** | `RED_CARD_FACTORS["LA_LIGA"]`. Blocked until now: La Liga had shots for 2025-26 only, and the 2021-25 Understat backfill (ADR-015) made multi-season calibration possible. |
| **Expected effect** | down < 1, up > 1. |
| **Data cutoff** | LA_LIGA 2021-26, single red card, minute 10–80. `scripts/experiment_redcard_calibration.py --league LA_LIGA` (same method as EPL/SERIE_A, remaining time via `remaining_share`). |
| **Evaluation method** | In-sample, as for EPL/SERIE_A. |
| **Result** | 204 usable matches: down 0.488, up 1.395. RPS 0.1398 → 0.1120 (+19.9%). |
| **Limitations** | In-sample only. |
| **Decision** | **Shipped.** All four live leagues now have red-card factors. |

## Related documents

- `docs/RESEARCH_PROTOCOL.md` — baselines, sample-size bar, and
  evaluation method every entry here is measured against.
- `docs/RESEARCH_CHARTER.md` — why negative results are preserved
  rather than discarded.
