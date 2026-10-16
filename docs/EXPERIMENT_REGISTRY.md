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

### 2026-10-08: Treat NULL goalkeeper saves as zero (Todoist `6hhr9v69Mw2hwmVf`)

| Field | Detail |
|---|---|
| **Hypothesis** | API-Football returns `saves: null` (not 0) for a keeper with no saves, so zero-save games are stored as NULL and dropped from PLAYER_SAVES' training label (`saves IS NOT NULL`) and from the rolling `p_saves_r5` (`AVG` skips NULL). Both are inflated; fixing them should improve over/under lines. |
| **Proposed change** | A. Label only: train on NULL → 0. B. Label and feature: also rebuild `p_saves_r5` with the zeros. Rule: NULL → 0 only for keepers with ≥ 45 min whose opponent shots on target − goals conceded ≤ 1; other NULLs stay unknown. |
| **Expected effect** | Lower Poisson deviance and log loss at the 3.5 line; mean predicted saves closer to actual. |
| **Data cutoff** | EPL, SERIE_A, MLS, LA_LIGA keepers with features (9,687 rows; 8,971 with saves, 724 NULL relabelled 0). Time splits at 2025-08-01, 2026-03-01 and 2026-06-01, trained on earlier games, scored on later ones. `scripts/experiment_saves_null_as_zero.py`. |
| **Evaluation method** | Same features and LightGBM Poisson params as `fit_player_saves_model`. Paired per-row deviance and log-loss differences against the production model on the same test rows, bootstrap 95% CIs. |
| **Result (premise)** | **Confirmed.** Five live API calls: the one NULL keeper had opponent shots on goal equal to goals conceded (0 saves). Across stored rows, NULL-saves keepers have shots on target − conceded of ≈ 0 (LA_LIGA n=324, mean −0.01; MLS n=402, mean 0.13), while non-NULL keepers average 3.2 on that gap, equal to their mean saves. Mean saves in training: LA_LIGA 3.13 → 2.87, MLS 3.30 → 3.07 when NULLs count as 0. `p_saves_r5` averages 3.21 in production vs. 2.99 with zeros. |
| **Result (model)** | **No detectable gain.** Split 2026-03-01 (n=1,286): log loss production 0.6639, A 0.6655, B 0.6654; B − production deviance −0.0023 [−0.0236, +0.0182], log loss +0.0015 [−0.0060, +0.0087]. Split 2025-08-01 (n=2,157): B − production deviance +0.0018 [−0.0142, +0.0176], log loss +0.0035 [−0.0023, +0.0093]. Split 2026-06-01 (n=647): +0.0059 [−0.0234, +0.0359], +0.0073 [−0.0036, +0.0183]. Calibration swings the other way: production over-predicts (mean saves 3.22–3.27 vs. actual 3.12; P(over 3.5) +2 points), A and B under-predict (≈3.00; −3 to −4 points). |
| **Limitations** | The relabelling rule is inferred from shot counts, not from a second data source. 15 NULL rows stay unknown. Test rows are mostly MLS and La Liga (EPL/SERIE_A ≈ 75 each at the main split). Point estimates vary by about ±0.001 between reruns (LightGBM row order), well inside the intervals. Saves per game may have drifted upward (test mean 3.12 vs. 3.0 in training with zeros), which would favour the biased model. |
| **Decision** | **Not promoted.** The data issue is real but fixing it does not measurably help, and it shifts the model from slightly high to slightly low. Revisit when EPL/SERIE_A have more keeper-games (the player-stats backfill adds ~1,900 Serie A and ~760 EPL matches), or if a direct calibration check at the 3.5 line shows a bias worth correcting. |

### 2026-10-14: Rest and fixture congestion adjustment to goal rates, EPL (Todoist `6hf54j2hMP87xjR7`)

| Field | Detail |
|---|---|
| **Hypothesis** | A team playing on short rest, or with more recent matches than its opponent, scores fewer goals than the Dixon-Coles rate implies. Rest is counted across all competitions, so a team coming off a midweek European tie is correctly tired. |
| **Proposed change** | Multiply each goal rate by `exp(b1*short_rest_own + b2*short_rest_opp + b3*congestion_diff)`. `short_rest` is 1 if the team's previous competitive match was 3 days or fewer ago. `congestion_diff` is own minus opponent matches in the prior 14 days, clipped to ±3. Ridge-penalized Poisson fit (penalty 1.0) with the baseline rate as an offset. No home-advantage term, since the baseline already has one. `scripts/experiment_rest_congestion.py`, fixtures from `futbol.team_fixtures` (migration 0042; league, cups and continental, friendlies excluded). |
| **Expected effect** | Small. Negative `b1`, `congestion_diff` coefficient negative, small RPS and log-loss gain. |
| **Data cutoff** | EPL only. Coefficients fit on 2023-24 and 2024-25 (757 matches). Scored once on the 2025-26 holdout (379 of 380 matches). Matches where either team has no prior fixture on record are dropped. Baseline is production settings (`dc_fit_settings`, 50/50 goals+xG blend per ADR-016), refit weekly walk-forward, using only data before each match. Run on `main` at `d892a70`. |
| **Evaluation method** | Paired per-match RPS and log-loss against the unadjusted baseline on the same holdout matches, bootstrap 95% CI on the difference. Diff is adjusted minus baseline, so positive is worse. |
| **Result** | Coefficients (log-rate): short_rest_own +0.020, short_rest_opp +0.071, congestion_diff -0.042. 17.4% of training team-matches were on short rest. Holdout RPS 0.2076 → 0.2083, diff +0.0007, 95% CI [-0.0018, +0.0032]. Log loss 1.0246 → 1.0281, diff +0.0035, 95% CI [-0.0036, +0.0107]. **No improvement:** both point estimates are slightly worse and both intervals include zero. The own-rest coefficient has the opposite sign to the hypothesis (+2.0% goals), and the opponent-rest coefficient is the largest (+7.1%). |
| **Limitations** | One league and one holdout season; no check across seasons or leagues. The ridge penalty (1.0) and the 3-day and 14-day thresholds were not tuned. This tests rest and congestion together, not one feature group at a time as the ticket asked, and does not include travel distance, time zones or national-team minutes. No comparison with the dynamic-rating candidate. Postponed fixtures are excluded by the finished-status filter. Coefficients come from 757 matches, so they are noisy; the opposite sign on own rest is not evidence of a real effect. Run once (34 seconds); per-match scores were written only to a temporary file, not committed. |
| **Decision** | **Not promoted.** Nothing beats the baseline on a held-out season, so the production rates are unchanged. Travel and time-zone features, the other three leagues (MLS is where the ticket expects the strongest effect) and a second EPL holdout season remain untested. Revisit with MLS before treating the idea as closed. |

### 2026-10-14: Rest and fixture congestion adjustment to goal rates, MLS (follow-up to the EPL entry above)

| Field | Detail |
|---|---|
| **Hypothesis** | Same as the EPL entry. The ticket expected the effect to be strongest in MLS. |
| **Proposed change** | Identical adjustment and fit to the EPL entry (`short_rest_own`, `short_rest_opp`, `congestion_diff`, ridge penalty 1.0, baseline as offset). `scripts/experiment_rest_congestion.py --league MLS --train 2024 2025 --holdout 2026`. Baseline is goals-only Dixon-Coles at production settings, refit weekly (MLS is not in `XG_BLEND_LEAGUES`). |
| **Expected effect** | Small, and larger than EPL if the ticket's expectation holds. |
| **Data cutoff** | Coefficients fit on the 2024 and 2025 seasons (1,044 matches). Scored once on the 2026 season to date (420 matches; the season was still in progress). `team_fixtures` covers 29–30 MLS teams in every year 2021–2026. Run on `main` at `d892a70`. |
| **Evaluation method** | Same as the EPL entry: paired per-match RPS and log loss against the unadjusted baseline, bootstrap 95% CI, diff is adjusted minus baseline (positive is worse). |
| **Result** | Coefficients (log-rate): short_rest_own +0.088, short_rest_opp -0.017, congestion_diff -0.038. 15.4% of training team-matches were on short rest. Holdout RPS 0.2255 → 0.2254, diff -0.0001, 95% CI [-0.0019, +0.0016]. Log loss 1.0628 → 1.0619, diff -0.0008, 95% CI [-0.0062, +0.0045]. **No detectable change:** the point estimates are marginally better, and both intervals are centred on zero and about as wide as the EPL ones. As in EPL, the own-rest coefficient has the opposite sign to the hypothesis (+9.2% goals), which suggests it is noise or confounded rather than a tiredness effect. |
| **Limitations** | All the EPL limitations apply: untuned ridge penalty and thresholds, rest and congestion tested together, no comparison with the dynamic-rating candidate, one holdout season. The 2026 holdout is a partial season. MLS has the effect the ticket was most interested in, travel distance and time zones, and this run does not test it. Fixture coverage is cup and league only; national-team call-ups are not in `team_fixtures`. |
| **Decision** | **Not promoted.** Together with the EPL entry, two leagues now show no measurable gain from rest and congestion at these definitions. Production rates are unchanged. SERIE_A and LA_LIGA were not run. A travel and time-zone feature set is the remaining untested part of Todoist `6hf54j2hMP87xjR7`. |

### 2026-10-14: Production Dixon-Coles baseline on the Bundesliga (spike before adding a league)

| Field | Detail |
|---|---|
| **Hypothesis** | The production Dixon-Coles setup (`dc_fit_settings` xi and ridge, goals-only) beats a league-average baseline on the Bundesliga without any league-specific change, so adding the league is a data and wiring task, not a modelling one. |
| **Proposed change** | None to production. `scripts/experiment_new_league_baseline.py` reads Bundesliga results from API-Football (league 78) and scores a weekly walk-forward fit offline. No database access; nothing written but a results cache. |
| **Expected effect** | RPS and log loss better than the naive baseline. |
| **Data cutoff** | 2021-22 to 2025-26 results, regular-season rounds only (306 matches and 18 teams per season; the API also lists the 1–2 relegation play-off matches in the league, which are excluded). Each holdout season is scored using only matches before each fit date, with seasons before it as history. |
| **Evaluation method** | Paired per-match RPS and log loss against the league-average home/draw/away rates of the history, bootstrap 95% CI on the difference (negative is better for DC). Matches involving a team with no history are skipped, as in production. |
| **Result** | 2023-24 (304 scored): RPS 0.2284 → 0.1965, diff -0.0320 [-0.0466, -0.0173]; LL 1.0786 → 0.9831, diff -0.0955 [-0.1393, -0.0485]. 2024-25 (301): RPS 0.2378 → 0.2157, diff -0.0222 [-0.0383, -0.0059]; LL 1.0983 → 1.0441, diff -0.0543 [-0.1087, +0.0015]. 2025-26 (305): RPS 0.2317 → 0.1957, diff -0.0360 [-0.0507, -0.0206]; LL 1.0696 → 0.9734, diff -0.0962 [-0.1440, -0.0455]. RPS improves with the interval clear of zero in all three holdouts; log loss in two of three. 2024-25 is the weak one: the home win rate fell to 38.5% while the model predicted 45.1% (realized home rate by season: 46.7, 47.4, 43.8, 38.6, 43.8%). |
| **Limitations** | The comparison is against a weak baseline (league-average rates); the protocol also asks for Elo and market-implied probabilities, and historical Bundesliga odds are not available from API-Football (current season only). Scores only: no xG blend, no props, no red-card or in-play factors. The first holdout has only two seasons of history. One league, one method. The RPS values are not directly comparable with the EPL or MLS entries above, which use other settings and holdouts. |
| **Decision** | **Baseline viable; no production change.** Dixon-Coles transfers to the Bundesliga. The xG blend, red-card factors and props each still need their own validated entry before the league goes live. Data found in the same spike: Understat has 306 of 306 matches with xG in every season 2021-25; API-Football xG is clean from 2023-24; the two sources use different club names. |

### 2026-10-14: Production Dixon-Coles baseline on Ligue 1 (spike before adding a league)

| Field | Detail |
|---|---|
| **Hypothesis** | Same as the Bundesliga entry above: the production Dixon-Coles setup beats a league-average baseline with no league-specific change. |
| **Proposed change** | None to production. `scripts/experiment_new_league_baseline.py --league-id 61 --first-season 2021 --holdouts 2023 2024 2025`. |
| **Expected effect** | RPS and log loss better than the naive baseline. |
| **Data cutoff** | API-Football regular-season results, 2021-22 to 2025-26: 380 matches in each of 2021-22 and 2022-23 (20 teams), then 306 (18 teams) in 2023-24 and 2024-25, and 305 in 2025-26. The one match missing from 2025-26 was not investigated. Same walk-forward and evaluation method as the Bundesliga entry. |
| **Evaluation method** | Same as the Bundesliga entry. |
| **Result** | 2023-24 (305 scored): RPS 0.2331 → 0.2146, diff -0.0186 [-0.0303, -0.0061]; LL 1.0878 → 1.0383, diff -0.0495 [-0.0846, -0.0128]. 2024-25 (306): RPS 0.2363 → 0.2081, diff -0.0282 [-0.0429, -0.0134]; LL 1.0542 → 0.9756, diff -0.0786 [-0.1216, -0.0334]. 2025-26 (304): RPS 0.2294 → 0.2064, diff -0.0230 [-0.0372, -0.0091]; LL 1.0640 → 0.9961, diff -0.0679 [-0.1092, -0.0282]. Both metrics improve with the interval clear of zero in all three holdouts. The league's outcome rates move a lot between seasons (home win 39.2% in 2023-24, 46.7% in 2024-25; draws 20.3% in 2024-25), and the model lags: in 2024-25 it predicted home 42.1% against 46.7% realized, draw 25.2% against 20.3%. |
| **Limitations** | Same as the Bundesliga entry: league-average baseline only, no Elo or market baseline, scores only (no xG, props, red-card or in-play factors), one method, and RPS not directly comparable with other leagues. The first holdout trains on 760 matches from two 20-team seasons, a different league shape from the 18-team seasons it is scored on. |
| **Decision** | **Baseline viable; no production change.** Dixon-Coles transfers to Ligue 1. Understat coverage and club-name mapping for Ligue 1 were not checked in this entry. |

### 2026-10-14: Production Dixon-Coles baseline on the Eredivisie (spike before adding a league)

| Field | Detail |
|---|---|
| **Hypothesis** | Same as the Bundesliga entry. The Eredivisie has no Understat coverage, so only the results-only baseline is testable. |
| **Proposed change** | None to production. `scripts/experiment_new_league_baseline.py --league-id 88 --first-season 2021 --holdouts 2023 2024 2025`. |
| **Expected effect** | RPS and log loss better than the naive baseline. |
| **Data cutoff** | API-Football regular-season results, 2021-22 to 2025-26: 306 matches and 18 teams in every season. Same walk-forward and evaluation method as the Bundesliga entry. |
| **Evaluation method** | Same as the Bundesliga entry. |
| **Result** | 2023-24 (305 scored): RPS 0.2314 → 0.1814, diff -0.0500 [-0.0665, -0.0339]; LL 1.0750 → 0.9232, diff -0.1519 [-0.2012, -0.1008]. 2024-25 (305): RPS 0.2286 → 0.1988, diff -0.0298 [-0.0475, -0.0112]; LL 1.0697 → 0.9833, diff -0.0864 [-0.1426, -0.0238]. 2025-26 (305): RPS 0.2277 → 0.1967, diff -0.0310 [-0.0475, -0.0150]; LL 1.0744 → 0.9871, diff -0.0873 [-0.1394, -0.0323]. Both metrics improve with the interval clear of zero in all three holdouts, with the largest gains of the three leagues tested the same day. Predicted and realized outcome rates track closely each season (for example 2024-25 predicted H/D/A 0.447/0.230/0.323 against 0.452/0.252/0.295 realized). |
| **Limitations** | Same as the Bundesliga entry. The large gain over the league-average baseline likely reflects how unequal the league is (a few clubs far stronger than the rest), which makes the naive baseline weak; it should not be read as the model being better here than elsewhere. No Understat xG exists for this league, so the xG blend could only use API-Football xG, which my 2026-10-14 sample found reliable from 2023-24 and unusable in 2021-22 and mostly in 2022-23; whether a blend helps is untested. |
| **Decision** | **Baseline viable; no production change.** The results-only model works for the Eredivisie. The xG question, props and red-card factors remain untested. |

### 2026-10-14: Pre-registration, Bundesliga: fixed 50/50 goals + xG blend (committed before any Bundesliga xG is in the database)

| Field | Detail |
|---|---|
| **Hypothesis** | The fixed 50/50 goals + xG blend from ADR-016 beats goals-only Dixon-Coles on Bundesliga 1X2, measured by RPS. |
| **Why this is an untouched test** | w = 0.5 was read off EPL and SERIE_A and confirmed on La Liga (ADR-016); no Bundesliga data was used to choose it. The only Bundesliga result seen so far is the goals-only baseline (entry above, commit c6c0954), which involves no xG. The Understat Bundesliga xG has been looked at only to count coverage (306 of 306 matches with both xG values in each of 2021-22 to 2025-26), not compared with outcomes. |
| **Proposed change** | None to production. Only `scripts/experiment_xg_blend.py` changes: its `--league` choices accept `BUNDESLIGA`. |
| **Test** | For each holdout season run `python scripts/experiment_xg_blend.py --league BUNDESLIGA --tune <previous season> --holdout <season> --fixed-w 0.5 --dump <file>.npy`, with holdouts 2022-23, 2023-24, 2024-25 and 2025-26 (weekly walk-forward; each fit uses only earlier seasons, so 2022-23 is trained on 2021-22 alone). Pool the per-match RPS differences (blend minus goals-only) across the four holdouts and take the bootstrap 95% CI, as for La Liga. |
| **Success criterion (fixed now)** | The pooled RPS-difference CI lies entirely below 0. Anything else is a fail and is recorded as a fail; the Bundesliga then stays goals-only. Log loss and the per-season differences are reported but are not the decision rule. |
| **Prerequisites** | Understat xG for 2021-22 to 2025-26 linked into `team_match_stats.xg` for the Bundesliga matches (backfill steps 2a and 2c). If any matches lack both xG values, the count is stated with the result and the test runs on the matches that have them. |
| **What this does not decide** | The scale of API-Football xG for the live 2026-27 season (existing leagues rescale it by x1.108; a Bundesliga factor needs its own estimate from matches that have both sources), and the red-card, in-play and props validations, which each get their own entry. Ligue 1 would get its own pre-registration. |
| **Decision if passed** | A follow-up ADR adds `BUNDESLIGA` to `XG_BLEND_LEAGUES`. Not done by this entry. |

### 2026-10-14: Result, Bundesliga fixed 50/50 goals + xG blend (the pre-registered test above)

| Field | Detail |
|---|---|
| **What was run** | Exactly the registered commands: `experiment_xg_blend.py --league BUNDESLIGA --tune <previous season> --holdout <season> --fixed-w 0.5 --dump ...` for 2022-23, 2023-24, 2024-25 and 2025-26, then the per-match RPS differences pooled and bootstrapped with the repo's `ci()` (2,000 resamples, seed 0). Run on the Bundesliga data loaded the same day: 1,530 matches with Understat team xG for all of them (steps 2a and 2c). |
| **Per-season result (blend minus goals-only RPS; negative is better)** | 2022-23 (304 matches): 0.2106 → 0.2069, diff -0.0038 [-0.0069, -0.0007]. 2023-24 (304): 0.1965 → 0.1957, diff -0.0007 [-0.0032, +0.0018]. 2024-25 (304): 0.2105 → 0.2072, diff -0.0033 [-0.0057, -0.0009]. 2025-26 (305): 0.1969 → 0.1953, diff -0.0015 [-0.0035, +0.0004]. All four seasons improved; two of the four intervals exclude zero on their own. |
| **Pooled result** | n = 1,217. RPS 0.2036 → 0.2013, diff **-0.0023, 95% CI [-0.0036, -0.0011]**. Log loss (secondary) 0.9994 → 0.9910, diff -0.0084, 95% CI [-0.0127, -0.0040]. |
| **Verdict against the pre-registered rule** | **Passed.** The pooled RPS interval lies entirely below 0. |
| **Limitations** | The 1,217 scored matches are 1,224 minus 7 whose teams had no earlier history (promoted clubs). The first holdout (2022-23) is fit on 2021-22 alone. The xG used is Understat's; the live 2026-27 season will use API-Football xG, whose rescale factor for this league has not been estimated. The reference-only weights in the script output (w = 0.75 and 1.0 score better still in three of the four seasons) were not used to change w = 0.5, which was fixed in advance. One match (Holstein Kiel v VfL Bochum, 2025-02-09) has team xG but no shot rows. |
| **Decision** | The pre-registered follow-up applies: an ADR adds `BUNDESLIGA` to `XG_BLEND_LEAGUES`. **Not done by this entry.** `tests/test_bundesliga_wiring.py` still guards that the set excludes it, and the change should ship with the league's launch together with the API xG scale factor. Red-card factors, the in-play remaining-goal share and props each still need their own entry. |

### 2026-10-15: Bundesliga in-play remaining-goal share and red-card multiplier

| Field | Detail |
|---|---|
| **Hypothesis** | (1) The empirical remaining-goal share (ADR-013, pooled from EPL and Serie A goals) transfers to the Bundesliga and beats the linear `(90 - minute) / 90` rule late in matches. (2) The Bundesliga shows the same 10-men effect as the other four leagues: down < 1 < up. |
| **Proposed change** | Add `BUNDESLIGA` to `EMPIRICAL_REMAINING_LEAGUES` and `RED_CARD_FACTORS` in `src/predictions/live_winprob.py`, and to the `red_card_calibrated` list in `api/main.py`. |
| **Expected effect** | Lower log loss at 85'+ than the linear rule (stoppage-time goals no longer ignored); down factor roughly 0.4-0.6, up factor roughly 1.4-1.8. |
| **Data cutoff** | Bundesliga 2021-22 to 2025-26, 1,530 matches, Understat goal minutes (`futbol.shots`). The curve itself is unchanged (EPL + Serie A, seasons other than the holdout), so for the Bundesliga this is a pure out-of-league test. Red cards: API-Football `fixtures/events` (read-only, 211 candidate matches). |
| **Evaluation method** | (1) `scripts/experiment_inplay_stoppage.py --league BUNDESLIGA` for holdouts 2025-26 and 2024-25 (271 matches each), linear vs empirical, RPS and log loss at 15' to 90'. (2) `scripts/experiment_redcard_calibration.py --league BUNDESLIGA`, single red between 10' and 80', actual vs expected remaining goals with the empirical curve; in-sample RPS check as for EPL, Serie A and La Liga. The calibration script was made read-only for this run. |
| **Result** | (1) Empirical beats linear late in both holdouts. Log loss, linear to empirical: 2025-26 85' 0.6019 to 0.5170, 89' 0.6069 to 0.4129, 90' 0.4965 to 0.3563; 2024-25 85' 0.3475 to 0.3398, 89' 0.3852 to 0.2921, 90' 0.3547 to 0.2754. Before 75' the two are close: in 2025-26 the empirical curve is equal or better at every checkpoint; in 2024-25 it is slightly worse from 15' to 80' (RPS +0.0003 to +0.0022, largest at 75'; log loss +0.001 to +0.016) and better from 85'. (2) 127 usable single-red matches (211 candidates; 17 multi-red and 67 outside 10'-80' skipped): down 0.528 (50 actual vs 94.7 expected goals), up 1.631 (162 vs 99.3). RPS 0.1471 to 0.1136 (+22.8%). Calibrated against the linear rule instead, the factors were 0.594 and 1.821, which is the stoppage-goal absorption ADR-013 warned about, so the curve was enabled first. |
| **Limitations** | The red-card factors are in-sample, like EPL, Serie A and La Liga. Two holdout seasons for the curve, one league. Mid-match checkpoints in 2024-25 are marginally worse with the empirical curve. Goal minutes come from Understat, as for the other leagues. |
| **Decision** | **Shipped on this branch (not deployed).** `BUNDESLIGA` joins `EMPIRICAL_REMAINING_LEAGUES` and `RED_CARD_FACTORS` (0.528, 1.631). The live poller does not run for the Bundesliga until the wiring branch is merged and deployed. |

### 2026-10-15: Bundesliga API-Football xG scale factor (Understat vs API-Football)

| Field | Detail |
|---|---|
| **Hypothesis** | API-Football `expected_goals` runs below Understat xG in the Bundesliga by about the same amount as in EPL, Serie A and La Liga (pooled ratio 1.108), so a single rescale factor can put live 2026-27 API xG on the Understat scale the blend was tested on. |
| **Proposed change** | A Bundesliga-specific scale for `store_api_football_xg` (today one constant, `API_FOOTBALL_XG_SCALE = 1.108`). **Not changed by this entry.** |
| **Data cutoff** | All 306 matches of each of 2023-24, 2024-25 and 2025-26 that have both sources (612 team-matches per season, 1,836 in total). API xG is clean from 2023-24, so earlier seasons are excluded. `scripts/experiment_api_football_xg.py --league BUNDESLIGA --season <s> --n 306`, read-only, about 920 API calls. |
| **Evaluation method** | Same as the 2026-10-03 entry: correlation, mean bias, regression slope, and the ratio of summed Understat xG to summed API-Football xG. |
| **Result** | Correlation 0.945, 0.938, 0.935. Ratio Understat / API-Football: 1.0876 (2023-24), 1.1145 (2024-25), 1.0846 (2025-26); **pooled 1.095** (3060.62 / 2794.59). Mean xG per team-match, Understat vs API: 1.668 vs 1.534, 1.630 vs 1.463, 1.702 vs 1.570. Regression API = 0.80-0.87 x Understat + 0.09-0.15. |
| **Limitations** | A ratio of sums is a single multiplicative scale; the regression has a positive intercept, so API xG is relatively higher for low-xG teams and the ratio is not constant across the range. The three seasons differ by up to 0.03. Only the ratio, not the blend, was re-tested with the rescaled values. The 2026-27 season has no Understat xG to check against. |
| **Decision** | **Proposed: 1.095 for the Bundesliga** (EPL, Serie A and La Liga keep 1.108). Not applied: it needs a per-league scale in `store_api_football_xg`, to ship with the blend ADR and the wiring branch. |

### 2026-10-15: Pre-registration, Bundesliga CORNERS and SOT props (committed before any Bundesliga props result)

| Field | Detail |
|---|---|
| **Hypothesis** | The live pooled props models (`fit_props_model` in `generate_slate.py`: LightGBM Poisson on rolling-5 team features, no league feature, trained on every league in `PROPS_LEAGUES` that has xG, which in practice is EPL, SERIE_A and LA_LIGA because MLS has no xG and is dropped) transfer to the Bundesliga for team CORNERS and shots on target (SOT), and adding Bundesliga rows to the training pool does not hurt the existing leagues. |
| **Proposed change** | Add `BUNDESLIGA` to the `leagues` of the CORNERS and SOT entries in `PROPS_MARKETS` (today both point at one shared `PROPS_LEAGUES` set, so a market that fails needs its own set). **Not made by this entry.** CARDS stays off (referee not known at slate time, separate task `6hgfHfQgJ4ffc2hf`). Player props are a separate validation. |
| **Expected effect** | Poisson log loss below a league-average baseline; calibrated over-probabilities within a few points of realized. |
| **Data cutoff** | Rows as in `fit_props_model` (`n_prior >= 5`, all features present). Bundesliga 2021-22 to 2025-26. Test A: holdouts 2025-26 (primary) and 2024-25 (consistency); training is existing-league rows kicking off before the holdout season's first kickoff (out-of-league: no Bundesliga row in training). Test B: existing leagues' rows kicking off on or after 2025-08-01, model trained before 2025-08-01 with and without the Bundesliga's earlier rows. |
| **Evaluation method** | `scripts/experiment_props_new_league.py`, run per market. Live hyperparameters; live-style out-of-fold (5-fold, seed 42) isotonic calibrators per line fit on the training rows only. Poisson log loss per team-match; differences bootstrapped over matches (both team rows of a match resampled together, 2,000 resamples, seed 0, 95% percentile interval). Baselines: the Bundesliga's own mean over its pre-holdout rows (primary), and the training pool's mean (secondary, reported). |
| **Decision rule (fixed now, per market)** | **R1 skill:** on the 2025-26 holdout the model beats the Bundesliga-own-mean baseline, with the 95% interval of (baseline loss minus model loss) entirely above 0; the 2024-25 holdout must have the same sign. **R2 calibration:** on the 2025-26 holdout, for every line, the calibrated quartile mean absolute gap is at most 0.05 (the threshold `train_props.py` already uses), and no 0.1-wide probability band with at least 100 rows has a stated-vs-realized gap above 0.07. **R3 non-inferiority:** in Test B the pooled log-loss change on existing leagues from adding the Bundesliga, (with minus without), has a 95% upper bound below +0.001. A market is promoted only if R1, R2 and R3 all hold for it; otherwise it stays off and the failure is the result. If CORNERS and SOT disagree, they get separate league sets. |
| **What this does not decide** | Live 2026-27 behaviour: the Bundesliga will have API-Football xG rescaled by 1.095, while this test uses Understat xG history. Not tested here. CARDS, player props and the emission band (`PROPS_OVER_BAND`/`PROPS_UNDER_BAND`) are out of scope. Live graded predictions still have to reach the 350 / 750 / 1,250 gates (ADR-017); this is historical validation and does not advance that clock. |
| **Limitations (known before running)** | Two holdout seasons, one league. xG features come from Understat in history. The pooled model has no league feature, so a league-level offset (the Bundesliga averages 4.9 corners per team-match, EPL 5.0-5.4) shows up as bias, which is why the Bundesliga-own mean is the primary baseline. |

### 2026-10-15: Result, Bundesliga CORNERS and SOT props (the pre-registered test above)

| Field | Detail |
|---|---|
| **What was run** | `scripts/experiment_props_new_league.py --league BUNDESLIGA --market CORNERS` and `--market SOT`, exactly the registered design, read-only. 14,302 rows: LA_LIGA 3,811, SERIE_A 3,781, EPL 3,775, BUNDESLIGA 2,935 (MLS contributes none: it has no xG, so the live query's `dropna()` removes it). Test A holdouts 2025-26 (607 rows) and 2024-25 (602). Test B: 2,636 existing-league rows from 2025-08-01. |
| **CORNERS, R1 skill** | **Pass.** 2025-26: Poisson log loss 2.4175 vs Bundesliga-own-mean 2.4723, gain +0.0547, 95% [+0.0177, +0.0943]. 2024-25: 2.4006 vs 2.4601, gain +0.0595, [+0.0193, +0.1019]. Mean predicted 4.99 vs actual 4.89 (2025-26). |
| **CORNERS, R2 calibration** | **Pass.** Calibrated quartile gap 0.026, 0.028, 0.025, 0.028 for Over 3.5, 4.5, 5.5, 6.5 (all at most 0.05). Largest gap in a band with n >= 100: -0.064 (Over 5.5, band 0.4-0.5, n=190), under the 0.07 limit. The 0.7-0.8 band that is overconfident for existing-league corners (Todoist `6hm4XP38mV4gGQ57`) holds for the Bundesliga: Over 3.5, n=193, stated 0.725 vs realized 0.699. |
| **CORNERS, R3 non-inferiority** | **Pass.** Adding the Bundesliga to the training pool changes existing-league log loss by -0.00827, 95% [-0.01221, -0.00431] (improves): EPL -0.01011, LA_LIGA -0.00920, SERIE_A -0.00550 (interval touches +0.00155). |
| **SOT, R1 skill** | **Pass.** 2025-26: 2.2797 vs 2.3496, gain +0.0700, [+0.0362, +0.1042]. 2024-25: 2.2555 vs 2.3107, gain +0.0551, [+0.0174, +0.0922]. But mean predicted 4.44 vs actual 4.77 in 2025-26 (4.48 vs 4.60 in 2024-25): the model under-predicts Bundesliga shots on target, and its pool mean (4.31) is well below the Bundesliga's own (4.7). |
| **SOT, R2 calibration** | **Fail.** Calibrated quartile gaps are within 0.05 (0.042, 0.042, 0.030, 0.039), but one band with n >= 100 breaks the 0.07 limit: Over 5.5, band 0.4-0.5, n=151, stated 0.427 vs realized 0.517, gap +0.089. Near the limit: Over 2.5 band 0.7-0.8, n=265, +0.069; Over 4.5 band 0.4-0.5, n=161, +0.069. Most bands lean the same way (realized above stated), consistent with the under-prediction. |
| **SOT, R3 non-inferiority** | **Fail by the registered threshold.** Pooled change -0.00212, 95% [-0.00567, +0.00132]; the upper bound is above +0.001. By league: EPL +0.00125 [-0.00409, +0.00720], LA_LIGA -0.00857 [-0.01569, -0.00160], SERIE_A +0.00115 [-0.00451, +0.00662]. The point estimate is an improvement; the interval is simply too wide to show non-inferiority at the registered margin. |
| **Limitations** | Two holdout seasons, one league. About 25 bands are examined per market against a 0.07 limit, so a single exceedance at n of 150 (standard error about 0.04) is not strong evidence on its own; the SOT failure is, however, backed by a systematic bias and the R3 miss. Understat xG features; live 2026-27 Bundesliga xG will be API-Football rescaled by 1.095, which this test does not cover. No league feature in the model, so league-level offsets are not modelled. The thresholds were fixed before the run and are not adjusted here. |
| **Decision** | **CORNERS: promotion criteria met; the code change is not made by this entry.** It needs `BUNDESLIGA` in the CORNERS `leagues` only (a new set, since SOT stays off) and the outer `league in PROPS_LEAGUES` gate in `generate_for_fixture` widened to any market's league set; `tests/test_bundesliga_wiring.py` still guards `PROPS_LEAGUES`. **SOT: not promoted.** Per the registered rule, CORNERS and SOT get separate league sets. A SOT follow-up would be a new pre-registered test of a league-level offset or a league feature, not a re-run of this one with looser thresholds. CARDS and player props remain untested and off. |

### 2026-10-15: Pre-registration, league-level offset for the pooled SOT model (committed before any offset result)

| Field | Detail |
|---|---|
| **Hypothesis** | The Bundesliga SOT failure above (R2 and R3) comes from the pooled model having no league term: the Bundesliga averages about 4.7 shots on target per team-match against 4.3 for the pool the model was fit on, so predictions run about 7% low and calibration bands lean the same way. Giving each league its own base level removes that bias without hurting the existing leagues. |
| **Proposed change** | Candidate model M2: the live LightGBM Poisson model (same features and hyperparameters, same 5-fold out-of-fold isotonic calibrators), fit on EPL, SERIE_A, LA_LIGA and BUNDESLIGA with a league-level offset: `init_score = log(mean of y over that league's training rows)` for each row, and `mu = model output x that league's mean` at prediction. The trees then learn only the structure around each league's own level. League means come from training rows only. Single variant, fixed here. **Not applied to the live pipeline by this entry.** |
| **Expected effect** | Bundesliga mean prediction within 3% of the realized mean; calibration inside the registered limits; no loss on existing leagues. |
| **Data cutoff** | Same rows and splits as the props pre-registration above: `n_prior >= 5`, all features present, so EPL, SERIE_A, LA_LIGA and BUNDESLIGA (MLS has no xG). Test A: Bundesliga holdouts 2025-26 (primary) and 2024-25, training on all four leagues' rows kicking off before the holdout season's first kickoff (the Bundesliga's earlier seasons are in the training pool, as they would be live). Test B: existing leagues' rows kicking off on or after 2025-08-01; M2 trained before 2025-08-01 on all four leagues, compared with M0, the current live model (existing leagues only, no offset, no Bundesliga). |
| **Evaluation method** | `scripts/experiment_props_league_offset.py --market SOT`, read-only. Poisson log loss per team-match, differences bootstrapped over matches (both team rows resampled together, 2,000 resamples, seed 0, 95% percentile interval). Bundesliga-own mean over its pre-holdout rows as the baseline. Reported but not gating: M1 (pooled with the Bundesliga, no offset) on the same Bundesliga holdouts, and the paired gain of M2 over M1. |
| **Decision rule (fixed now)** | **R1 skill:** on 2025-26, M2 beats the Bundesliga-own mean with the 95% interval of the gain entirely above 0; 2024-25 same sign. **R2 calibration:** on 2025-26, for every line the calibrated quartile mean absolute gap is at most 0.05, and no 0.1-wide probability band with at least 100 rows has a stated-vs-realized gap above 0.07. **R3 non-inferiority:** over the existing leagues' rows in Test B, the log-loss change of M2 minus M0 has a 95% upper bound below +0.001 (the same margin as the props pre-registration, not loosened). **R4 bias:** on 2025-26, the Bundesliga mean predicted is within 3% of the mean actual. Promote only if R1 to R4 all hold. If any fails, the offset is not adopted and that is the result. |
| **What this does not decide** | Applying the offset to the live pipeline: that changes SOT predictions for the existing leagues and would need its own change, an ADR and a model-version bump. Corners (which passed without an offset), CARDS and player props. Live 2026-27 behaviour: the Bundesliga's xG will be API-Football rescaled, not Understat. |
| **Limitations (known before running)** | The R3 margin of +0.001 is demanding at this sample size: the Bundesliga props test had an interval about 0.007 wide on 2,636 rows, so passing needs an actual gain or a tighter interval, not just no harm. Two holdout seasons, one league. League means are fit on all training rows including those used for the isotonic calibrators' folds (one parameter per league, negligible leakage). A league with little history gets a noisy offset; not an issue for these four leagues. |

### 2026-10-15: Result, league-level offset for the pooled SOT model (the pre-registered test above)

| Field | Detail |
|---|---|
| **What was run** | `scripts/experiment_props_league_offset.py --market SOT`, exactly the registered design, read-only. 14,302 rows (LA_LIGA 3,811, SERIE_A 3,781, EPL 3,775, BUNDESLIGA 2,935). League means in the 2025-26 fit: BUNDESLIGA 4.691, EPL 4.599, LA_LIGA 4.149, SERIE_A 4.176. Sanity check passed: the offset model reproduces the training mean (4.389 vs 4.389). |
| **R1 skill** | **Pass.** 2025-26: M2 log loss 2.2562 vs Bundesliga-own mean 2.3496, gain +0.0934, 95% [+0.0586, +0.1295]. 2024-25: gain +0.0539 [+0.0152, +0.0951]. |
| **R2 calibration** | **Pass.** Calibrated quartile gaps 0.018, 0.028, 0.016, 0.039 (Over 2.5, 3.5, 4.5, 5.5). No band with n >= 100 above 0.07 (largest 0.031). The earlier failing band (Over 5.5, 0.4-0.5) is now stated 0.439 vs realized 0.438, n=146. Bands outside the rule's reach (n < 100) show larger gaps, for example -0.114 (Over 3.5, 0.4-0.5, n=58). |
| **R4 bias** | **Pass.** 2025-26 mean predicted 4.770 vs mean actual 4.774 (-0.1%). |
| **R3 non-inferiority** | **Fail.** M2 minus the live model M0 on 2,636 existing-league rows since 2025-08-01: +0.00274, 95% [-0.00233, +0.00751]; the upper bound is far above +0.001. By league: EPL +0.01157 [+0.00147, +0.02219] (worse, interval excludes 0), LA_LIGA +0.00185 [-0.00714, +0.01102], SERIE_A -0.00507 [-0.01228, +0.00233]. |
| **Why R3 failed (diagnosis, not part of the rule)** | A fixed league level goes stale when a league drifts. The EPL offset is its all-history training mean, 4.60 shots on target per team-match, but EPL averaged 4.19 in 2025-26 (all rows, from the feature table), so M2 over-predicts it. M0 has no level term and follows the drift through its rolling features. The same mechanism shows in 2024-25: M2 over-predicted the Bundesliga by 4.7% (4.819 vs 4.603), where M1 was within 0.7%. |
| **Exploratory, not gating, not a pre-registered result** | M1 (Bundesliga rows in the training pool, no offset) is the configuration the live pipeline would actually run. On these holdouts it is closer to unbiased than the out-of-league test suggested: mean predicted 4.521 vs 4.774 actual (-5.3%) in 2025-26 and 4.569 vs 4.603 (-0.7%) in 2024-25, log-loss gain over the own mean +0.0893 [+0.0545, +0.1252] and +0.0604. M2 over M1: +0.0041 [-0.0064, +0.0147] and -0.0066 [-0.0167, +0.0040], neither distinguishable from zero. The props pre-registration's Test A was deliberately out-of-league (no Bundesliga row in training), so it does not describe M1. M1's calibration was not examined. |
| **Limitations** | Two holdout seasons, one league. The R3 margin of +0.001 is the same as before and is demanding for 2,636 rows (interval widths of 0.007-0.01), so a model that is merely no worse will not pass it. Single offset variant (fixed league mean). No time-local offset (for example a trailing-season mean) was tried; that would be a new variant and a new pre-registration. |
| **Decision** | **Offset not adopted; SOT stays off for the Bundesliga.** No change to the live pipeline. Open options, each needing its own pre-registration and none run here: (a) test M1 itself (Bundesliga in the pool, no offset) on the production configuration; (b) a time-local offset; (c) revisit the R3 margin, which is a judgment about acceptable risk to the existing leagues rather than a statistical question. |

### 2026-10-15: Pre-registration, Bundesliga in the training pool with no offset (production configuration), SOT and CORNERS

| Field | Detail |
|---|---|
| **Hypothesis** | The configuration the live pipeline would actually run, the pooled model trained on EPL, SERIE_A, LA_LIGA **and BUNDESLIGA** with no league term (call it M1), is accurate and calibrated on the Bundesliga. The earlier props test was out-of-league (no Bundesliga row in training) and so did not describe it. |
| **What has already been seen (disclosed before this entry's run)** | From the league-offset run: for SOT, M1 predicted a mean of 4.521 vs 4.774 actual (-5.3%) in 2025-26 and 4.569 vs 4.603 (-0.7%) in 2024-25, with log-loss gain over the Bundesliga-own mean of +0.0893 [+0.0545, +0.1252] and +0.0604. For SOT, the existing-league non-inferiority comparison below is the same computation as Test B of the props pre-registration (Bundesliga added, no offset, same data and seed): -0.00212, 95% [-0.00567, +0.00132]. So for SOT, R1 is expected to pass, R3 is already known to miss the registered +0.001 margin and R4 is expected to miss the 3% limit at 2025-26. **What is genuinely new: M1's calibration (R2) for SOT, and every number for CORNERS in this configuration.** This entry does not pretend otherwise and does not change any threshold. |
| **Proposed change** | None to production by this entry. CORNERS is already enabled for the Bundesliga on the strength of the out-of-league test; this checks the configuration it actually runs. SOT would need `BUNDESLIGA` in the SOT `leagues` set. |
| **Data cutoff** | Same rows and splits as the props pre-registration: `n_prior >= 5`, all features present (EPL, SERIE_A, LA_LIGA, BUNDESLIGA; MLS has no xG). Test A: Bundesliga holdouts 2025-26 (primary) and 2024-25; training on all four leagues' rows before the holdout season's first kickoff, so the Bundesliga's earlier seasons are in the pool. Test B: existing leagues' rows on or after 2025-08-01; M1 trained before that date with the Bundesliga's earlier rows, compared with M0, the current live model without it. |
| **Evaluation method** | `scripts/experiment_props_pool_only.py --market SOT` and `--market CORNERS`, read-only. Live features, hyperparameters and 5-fold out-of-fold isotonic calibrators. Poisson log loss per team-match, differences bootstrapped over matches (both team rows resampled together, 2,000 resamples, seed 0, 95% percentile interval). Baseline: the Bundesliga-own mean over its pre-holdout rows. |
| **Decision rule (identical to the earlier pre-registrations, per market)** | **R1 skill:** on 2025-26, M1 beats the Bundesliga-own mean with the 95% interval of the gain entirely above 0; 2024-25 same sign. **R2 calibration:** on 2025-26, every line has a calibrated quartile mean absolute gap of at most 0.05 and no 0.1-wide band with at least 100 rows has a stated-vs-realized gap above 0.07. **R3 non-inferiority:** the 95% upper bound of (M1 minus M0) log-loss change over existing-league rows is below +0.001. **R4 bias:** on 2025-26 the mean prediction is within 3% of the mean actual. A market is promoted only if R1 to R4 all hold. For CORNERS, which is already enabled, a failure here means the enablement must be revisited, not that the earlier result is erased. |
| **What this does not decide** | Whether the +0.001 margin is the right one: it is a judgment about acceptable risk to the existing leagues, not a statistical result, and is left for the owner. Live 2026-27 behaviour (the Bundesliga's xG will be API-Football rescaled). CARDS and player props. |
| **Limitations** | Two holdout seasons, one league. As disclosed, part of the SOT outcome is already known, so the SOT verdict is not independent evidence for R1, R3 or R4. The R3 margin is demanding at about 2,600 test rows. |

### 2026-10-15: Result, Bundesliga in the training pool with no offset (the pre-registered test above), SOT and CORNERS

| Field | Detail |
|---|---|
| **What was run** | `scripts/experiment_props_pool_only.py --market SOT` and `--market CORNERS`, exactly the registered design, read-only. 14,302 rows. M1 = EPL, SERIE_A, LA_LIGA and BUNDESLIGA in the pool, no league term. |
| **SOT** | **R1 pass:** 2025-26 gain over the Bundesliga-own mean +0.0893 [+0.0545, +0.1252]; 2024-25 +0.0604 [+0.0219, +0.1005]. **R2 fail:** calibrated quartile gaps 0.036, 0.043, 0.026, 0.026 are within 0.05, but two bands with n >= 100 exceed 0.07: Over 3.5, 0.5-0.6, n=177, +0.070 (just over), and Over 5.5, 0.4-0.5, n=111, stated 0.452 vs realized 0.550, +0.098. **R3 fail:** -0.00212, 95% [-0.00567, +0.00132] (the same computation as the earlier props Test B; known in advance). **R4 fail:** predicted 4.521 vs 4.774 actual, -5.3% (known in advance; in 2024-25 it was -0.7%). **Verdict: not promoted.** |
| **CORNERS (already enabled on the branch)** | **R1 pass:** 2025-26 +0.0502 [+0.0150, +0.0889]; 2024-25 +0.0600 [+0.0212, +0.1016]. **R3 pass:** -0.00827 [-0.01221, -0.00431] (EPL -0.01011, LA_LIGA -0.00920, SERIE_A -0.00550). **R4 pass:** predicted 4.947 vs 4.893, +1.1% (+1.9% in 2024-25). **R2 fail:** quartile gaps 0.019, 0.017, 0.046, 0.031 are within 0.05, but one band with n >= 100 exceeds the limit: Over 5.5, 0.2-0.3, n=149, stated 0.267 vs realized 0.181, gap -0.086. Next worst: Over 6.5, 0.4-0.5, n=23 (-0.073, below the n >= 100 floor). **Verdict by the registered rule: DO NOT PROMOTE.** As registered, this means the corners enablement must be revisited. |
| **Post-hoc analysis of the R2 rule (not pre-registered; labelled so)** | The band criterion (any band with n >= 100 differing from stated by more than 0.07) has a large false-failure rate at these band sizes. Simulating perfect calibration with the 12 corners bands that have n >= 100 (sizes 118 to 271, stated probabilities 0.17 to 0.73), at least one band exceeds 0.07 in **51%** of 20,000 simulations; with the 12 SOT bands, **50%**. A band of n=150 has a sampling standard error of about 0.036, so 0.07 is about 2 standard errors, and the rule applies it to a dozen bands. So an R2 failure on one band is close to a coin flip even for a perfectly calibrated model, and the rule also let the corners out-of-league test pass partly by luck. The simulation treats bands as independent, though bands from different lines overlap. The Over 5.5 corners miss is 2.4 standard errors; the SOT Over 5.5 0.4-0.5 miss is 2.1. |
| **What this does and does not change** | It does not change the registered verdicts above, and thresholds are not adjusted after the fact. It does mean R2 as written cannot separate a miscalibrated model from a good one, so neither the earlier SOT R2 failure nor this CORNERS failure is strong evidence of miscalibration, and the earlier CORNERS pass is not strong evidence of calibration. A replacement criterion (for example a calibration slope and intercept test, or a band test that requires the gap to exceed about 2.5 standard errors as well as 0.07) would need its own pre-registration and a re-evaluation of all four props results on the same footing. SOT's other findings stand: the -5.3% bias in 2025-26 and the R3 miss are not band-count artefacts. |
| **Limitations** | Two holdout seasons, one league. Part of the SOT outcome was disclosed as known before the run. Simulation ignores correlation between lines. |
| **Decision** | **SOT: not promoted; stays off.** **CORNERS: by the registered rule not promoted; enablement flagged for revisit.** No change is merged or deployed: the corners enablement exists only on branch `feat/bundesliga-props` (a90c902), not on `feat/bundesliga-integration`. Recommended next step, awaiting the owner: pre-register a calibration criterion that accounts for sampling error and apply it to CORNERS and SOT together, instead of choosing between the current verdicts. |

## Related documents

- `docs/RESEARCH_PROTOCOL.md` — baselines, sample-size bar, and
  evaluation method every entry here is measured against.
- `docs/RESEARCH_CHARTER.md` — why negative results are preserved
  rather than discarded.
