# futbol-modelo — Architectural Decision Records

Petey has its own ADR trail (`docs/adr/petey-decisions.md`). This file
covers everything else: the modeling, ledger, and pipeline decisions
that don't have anywhere else to live. Same format — Context, Decision,
Consequences — and the same rule: once accepted, an entry isn't edited
in place. A later ADR supersedes it and says so explicitly.

---

## ADR-001: Dixon-Coles for match outcomes, not a generic classifier

**Status:** Accepted

**Context:** 1X2/BTTS/total-goals could be modeled as independent
classification/regression problems (predict home win probability
directly, predict over/under directly, etc.), which is simpler to
implement and easier to swap models on.

**Decision:** Fit a single time-decayed bivariate Poisson model per
league (`src/models/dixon_coles.py`) — each team gets an attack and
defence rating, one fixture produces one scoreline probability matrix,
and every market (1X2, totals, BTTS) is *derived* from that same matrix
rather than fit separately.

**Consequences:** Markets can't contradict each other the way
independently-fit classifiers can (e.g. "60% home win" and "55% under
2.5 goals" that don't actually correspond to a coherent scoreline
distribution). The cost is that everything routes through one model:
a bug in the scoreline matrix propagates to every derived market at
once — which is exactly what `tests/test_dixon_coles_invariants.py`'s
property-based tests exist to catch before it reaches production.

---

## ADR-002: The prediction ledger is append-only, enforced by trigger

**Status:** Accepted

**Context:** A "calibration curve" claim is only meaningful if the
predictions it's built from can't have been edited after the fact —
otherwise there's no way to distinguish a genuinely well-calibrated
model from one that got quietly corrected after seeing results.

**Decision:** `predictions` rejects UPDATE and DELETE via
`forbid_prediction_mutation()` (a real trigger, not just a code-level
convention), and a second trigger rejects any insert locked at or after
kickoff. Corrections never touch the original row — they're a new
row in `prediction_grades` (e.g. `outcome = 'void'`) explaining what
happened, with the original claim still sitting there, unedited, for
anyone to check.

**Consequences:** Every historical bug this ledger has hit (duplicate
matches from kickoff-drift, a NaN silently breaking a JSONB insert)
had to be *worked around* rather than quietly fixed by editing old
rows — see `sql/void_duplicate_match_predictions.sql` for what that
actually looks like in practice. It's slower and more annoying than
`UPDATE ... WHERE`, which is the entire point.

---

## ADR-003: Isotonic calibration over Platt scaling for props

**Status:** Accepted

**Context:** Raw Poisson-derived probabilities from the LightGBM props
models (`src/models/props.py`) are usually miscalibrated in a way
that isn't a simple sigmoid shift — the direction and size of the
miscalibration can differ by line and by how confident the raw
prediction already is, which is exactly what Platt scaling (fit a
single logistic curve) assumes away.

**Decision:** Fit `IsotonicRegression` per market/line, on
out-of-fold predictions only — never on the same folds the underlying
model trained on. The comment in `props.py` is direct about why this
matters: "the isotonic calibrator is what makes stated probabilities
honest."

**Consequences:** Isotonic needs more data to fit well than a
two-parameter logistic curve, which is part of why per-line
calibrators (rather than one calibrator per market) are only trained
where there's enough support. It also means a probability like "73%"
is never the model's raw output — it's already been checked against
how often similar raw outputs actually came true, out of sample. This
is the one lesson-learned entry worth re-reading: this exact layer
existed, tested, and validated in a standalone script for weeks while
the real nightly pipeline kept shipping raw Poisson probabilities,
because it had never actually been wired into `generate_slate.py`.

---

## ADR-004: MLS as the primary league, not EPL/Serie A

**Status:** Accepted

**Context:** The project could have led with a "big European league"
for name recognition, or split effort evenly across all four leagues
from day one.

**Decision:** MLS gets the full feature set first — player props
(goals, saves), the primary live-score source, and the deepest
`team_match_features` coverage. EPL, Serie A, and La Liga get match
markets (1X2/BTTS/totals/corners/SOT) but not player props yet.

**Consequences:** Real, current tradeoff: MLS's live data path
(`backfill_primary()`) depends on a single paid API tier being active
(see the "API-Football free plan" incident) with no coded fallback,
while EPL/Serie A/La Liga can also fall back to the free FBref/Understat
scrapers in `loader.py`. Choosing a primary league that's more, not
less, dependent on one paid source was a real cost of this decision —
worth remembering the next time that API bill comes up for renewal.

---

## ADR-005: Match identity is the natural key, then external_ref, never kickoff alone

**Status:** Accepted

**Context:** A match's kickoff time can genuinely change between
ingestion runs (broadcast rescheduling, timezone corrections from the
source). Early upsert logic used
`(season_id, home_team_id, away_team_id, kickoff_utc)` as the sole
conflict target — which treats a kickoff-time correction as a *new*
fixture, not an update to the existing one.

**Decision:** `upsert_match()` looks up by `external_ref` first (a
stable per-source identifier), only falling back to the natural key
when no `external_ref` match exists. `idx_matches_external_ref` is a
partial unique index (`WHERE external_ref IS NOT NULL`) enforcing this
at the database level, not just in application code.

**Consequences:** This decision exists because skipping it produced a
real incident: 9 fixtures duplicated across two rows each after a
kickoff-time correction, splitting 139 predictions across an
orphaned row that grading could never find. The fix couldn't delete
the orphaned rows (ADR-002) — it could only void their predictions and
mark the matches `canc` so they stop resurfacing as live fixtures.
Getting the identity logic right the first time is cheaper than this.

---

## ADR-006: Manual, registry-less Kubernetes deploys

**Status:** Accepted

**Context:** A proper CI/CD pipeline with an image registry is the
conventional choice, but this cluster runs on homelab hardware with no
external registry and no CI runner budget.

**Decision:** Build on `docker-host`, `docker save` to a tar,
transfer, `k3s ctr images import` directly into the node's containerd,
`imagePullPolicy: Never` everywhere. See CLAUDE.md's real deploy
workflow.

**Consequences:** No rollback-by-tag and no way for anyone but the
node itself to pull the image — a stale tar reused without rebuilding
is a real, easy mistake (documented explicitly in CLAUDE.md because it
has happened). The `[FIXED] Site outage` incident was exactly this
class of problem at a different layer: a live DB schema change with no
corresponding image rebuild. `k8s/cronjobs.yaml` existing at all is a
direct consequence of this decision's fragility — those manifests used
to exist only as ad-hoc `kubectl apply` runs, invisible to git.

---

## ADR-007: Numbered SQL migrations, not an ORM migration framework

**Status:** Accepted

**Context:** For most of this project's life, schema changes landed as
ad hoc one-off scripts in `sql/` (`fix_duplicate_teams.sql`,
`add_pipeline_runs_table.sql`, `rename_goals_to_score.sql`, and eight
others) applied by hand against the live database, with `schema.sql`
manually kept in sync as a "current state" snapshot. Nothing forced
the two to agree — the missing `predictions` UNIQUE constraint (see
ADR-005) is a direct symptom of that drift. The alternative was
adopting alembic or yoyo, which pull in an ORM-adjacent dependency
graph this project otherwise avoids (see ADR-006's registry-less
deploys, and the frontend's SVG-over-charting-library choices).

**Decision:** `sql/migrations/NNNN_description.sql`, applied in
filename order by `scripts/migrate.py`, tracked in a `schema_migrations`
table — about 60 lines of plain psycopg2, no framework. `schema.sql`
stays the canonical from-scratch reference and must be updated by hand
alongside each new migration (enforced by convention in
`sql/migrations/README.md`, not by tooling). The twelve pre-existing
ad hoc scripts aren't retroactively renumbered into this sequence —
they already ran; `0001_baseline.sql` is a deliberate no-op marking
everything before this decision as already live.

**Consequences:** Schema changes now have exactly one path: a numbered
file, applied once, recorded permanently — the same "verify against
the real, currently running code" discipline the ledger and the
deploy workflow already enforce, just applied to the schema itself.
The cost is the same one ADR-006 accepts: no framework means no
auto-generated down-migrations or diffing — a wrong migration is fixed
by writing a new one, not by rolling back, which is a deliberate
match to the ledger's own append-only philosophy (ADR-002).

---

## ADR-008: Prediction/grading corrections are new rows, model/methodology changes are new versions — never silent rewrites

**Status:** Accepted

**Context:** ADR-002 already establishes that the `predictions` table
itself is append-only. What was never written down explicitly is the
*full* set of rules for the situations that actually come up in
practice: a postponed or cancelled match, a data correction discovered
after grading, and a model or methodology change — each of which could
be handled correctly or incorrectly within the append-only constraint,
and the difference isn't obvious from the schema alone.

**Decision:** Formalizing what the codebase already does in practice,
as an explicit contract (see `docs/PLATFORM_CONTRACT.md`'s
"Methodology versioning" section for the full policy this ADR
anchors):

1. **Postponed/cancelled matches:** the match row is marked `canc` (or
   equivalent); any predictions already locked against it are voided
   via a new `prediction_grades` row, never deleted. This is exactly
   what the real 2026-08-27/28 duplicate-match incident required (see
   ADR-005) — 9 fixtures' orphaned predictions were voided, not erased.
2. **Data corrections discovered after grading:** a correction never
   edits the original `predictions` or `prediction_grades` row. It is
   a new `prediction_grades` row (e.g. `outcome = 'void'`) with enough
   context to explain what happened, exactly as ADR-002 already
   requires — this ADR just states it applies to *every* correction
   source (a bad upstream data point, a scoring error, a duplicate),
   not only to duplicate-match cleanup specifically.
3. **Model version changes:** every prediction is tied to a
   `model_version_id` (ADR-005's registry). Swapping which model is
   live for future slates never touches past predictions' version
   references — a model's entire graded history stays attributed to
   the version that actually produced it.
4. **Methodology changes** (a change to how a market is modeled,
   calibrated, or graded — distinct from a routine retrain): requires
   both a new `model_versions` row *and* an ADR if architectural (this
   document's own convention — ADR-003's isotonic-calibration switch
   is the precedent), plus an entry in `docs/EXPERIMENT_REGISTRY.md`
   if it started as a hypothesis under `docs/RESEARCH_PROTOCOL.md`.
5. **Correction history is public, not swept into the original
   claim's row.** The Track Record page's calibration/scorecard views
   already read from `prediction_grades`, so a voided or corrected
   prediction's history is visible in the same place a clean one is —
   there is no separate, hidden "corrections log."

**Consequences:** No prior claim can be quietly rewritten to look
better after the fact, for any of the reasons corrections normally
happen (bad data, bad match state, a bad model) — the same guarantee
ADR-002 gives for simple edits now explicitly covers the messier real
cases. The cost is the same one ADR-002 already accepts: every
correction is slower and more visible than `UPDATE ... WHERE`, which
is the entire point.

---

## ADR-009: NBA cross-sport expansion — retired, not continued, as of 2026-09-21

**Status:** Accepted

**Context:** The original multi-sport comparison plan considered NBA
alongside NFL as a candidate third sport, and a real NBA vertical
slice was in fact built and shipped — `src/models/nba_power_ratings.py`
and `src/models/nba_player_points.py`, predicting `TOTAL_POINTS` and
`PLAYER_POINTS` (see `README.md`, `CLAIMS.md`; live-verified 2026-09-06
against 1230 real 2025-26 games). The open question was whether to
continue investing in NBA as one of the platform's core cross-sport
comparison points, alongside soccer and NFL.

**Decision:** Soccer and NFL remain the platform's primary structural
contrast (continuous clock vs. discrete downs, frequent low-variance
scoring vs. infrequent high-variance scoring, draws exist vs. don't —
see `docs/RESEARCH_CHARTER.md`). Further NBA expansion work beyond the
already-shipped `TOTAL_POINTS`/`PLAYER_POINTS` slice is not being
pursued. The shipped model is not deleted or deprecated — it keeps
running, keeps getting graded, and stays visible on the Track Record
page with its honest uncalibrated status — but it is not receiving the
calibration, player-props expansion, or market-line work the other
sports are getting.

**Consequences:** NBA is intentionally retired from further
*expansion*, not silently abandoned — this ADR is the record of why.
Anyone revisiting cross-sport scope later has a real decision to
un-make here, not an unexplained gap to reverse-engineer from git
history. Soccer and NFL's structural contrast (continuous vs. discrete
play, scoring frequency, draws) was judged the stronger comparison for
`docs/RESEARCH_CHARTER.md`'s central question than adding a third,
higher-scoring, near-continuous-possession sport on top of it, given
NBA's own player-availability and calibration data-gap costs were
already the same as NFL's without a comparably distinct structural
payoff.

---

## ADR-010: close-to-kickoff "final pass" for player-prop markets — the
first prediction-refresh mechanism in this codebase

**Status:** Accepted

**Context:** The lineup/injury-news feature (Todoist: "futbol-modelo:
lineup/injury news as a model feature", Phase 2) hit the same timing
gap CARDS' `referee_avg_cards_r10` feature already hit: a real
confirmed absence is only reliably known ~1-2 hours pre-kickoff, but
`auto_slate.py` generates each fixture's slate once, 7-45 days out
depending on league, and `generate_for_fixture()` hard-blocks ever
re-slating the same `match_id` (a real duplicate-slate incident sits
behind that guard). CARDS' answer — fall back to a training-set-wide
average at inference time — is honestly weaker than a true confirmed-
absence signal, and was accepted as the baseline here too
(`player_injury_features.absence_rate_r10`, `resolve_absence_feature()`
in `scripts/generate_slate.py`). But unlike referee (never knowable
ahead of a fixture, full stop), lineup/injury status genuinely becomes
knowable in the hours before kickoff — discarding that improvement
once it exists was a real, avoidable gap, not an architectural
necessity.

**Decision:** For `PLAYER_GOALS`/`PLAYER_SAVES` only, a new CronJob
(`futbol-props-final-pass`, every 15 min) polls the real `/injuries`
endpoint for fixtures kicking off within ~2 hours and, when a fresher
signal is available, writes a **second, additive** prediction under a
distinct `model_version_id` (`player_props_lineup_confirmed_v1`) —
never a rewrite of the original slate row
(`generate_final_pass_for_fixture()`, deliberately not sharing
`generate_for_fixture()`'s one-slate-ever guard, which exists to catch
an *accidental* double-slate, not to block this *intentional* one).
This keeps ADR-002 (append-only ledger) and ADR-008 (corrections are
new rows, never rewrites) fully intact — the original prediction stays
in the ledger forever, exactly as inserted.

The final pass is the **official** prediction once it exists: both
`v_graded_predictions` (the calibration/Track Record source) and
`api/main.py`'s `get_slate()` (the live site) apply the same tie-break
— prefer `player_props_lineup_confirmed_v1` over the base model
version for the same natural key
(`sql/migrations/0036_final_pass_tiebreak.sql`). Two rows under the
*same* model version still resolve earliest-wins, so the original
duplicate-slate protection is unchanged for the case it exists to
catch — this ADR only changes behavior when the second row is
genuinely the intentional final-pass one.

**Consequences:** This is the first prediction-refresh mechanism ever
built in this codebase — every other market still gets exactly one
slate, ever. Scoped deliberately narrow (two markets, one new model
version, one new CronJob) rather than generalized into a platform-wide
"refresh" concept, since the timing justification (lineup data becomes
knowable close to kickoff; nothing else currently does) doesn't hold
for any other market today. A future market with a similar
close-to-kickoff-only signal should get its own ADR reusing this
pattern, not an assumption that this mechanism generalizes silently.
Real cost: `futbol-props-final-pass` runs far more frequently (every 15
min) than any other CronJob here, and burns real API-Football quota
per tick even when nothing qualifies — worth watching over the first
week of live operation.

One honest asymmetry, backtested 2026-09-29
(`docs/EXPERIMENT_REGISTRY.md`): `absence_rate_r10` only actually beat
baseline for `PLAYER_GOALS` (+0.33% log-loss); `PLAYER_SAVES` regressed
(-0.12%) on a much smaller goalkeeper sample and was deliberately left
out of `fit_player_saves_model()`. The final-pass mechanism still runs
for `PLAYER_SAVES` too (fresh `current_form`, same model), just gets no
benefit from the `/injuries` poll specifically until that market's own
sample grows enough to revisit.

---

## ADR-011: in-play win-probability — conditioned Dixon-Coles, not a new model class

**Status:** Accepted

**Context:** Todoist's "in-play/live win-probability updates" ticket
(Phase 3) was scoped from the start as "the hardest item — real-time
pipeline, different model class than everything else built so far."
Offline validation (2026-09-30,
`scripts/experiment_inplay_dixon_coles.py`) found that assumption
wrong: Dixon-Coles already fits per-team goal rates (λ home, μ away)
for a full match. Re-deriving a scoreline distribution for the
*remaining* time only (λ/μ scaled by the fraction of the match left),
then combining with the already-banked current score, reuses the exact
same fitted model — no new architecture. Validated against real
historical goal-minute data (`futbol.shots`, Understat-sourced, used
only as an offline backtest proxy — nothing here is live yet): beats
the static pre-match probability at every checkpoint (15'/30'/45'/60'/
75') for EPL, SERIE_A, and LA_LIGA (LA_LIGA only after fixing a real,
separate bug — see below). An ablation showed Dixon-Coles' low-score
correction (ρ), fit for a full 90' match, changes in-play results in
the 4th decimal place — dropped as not worth the untested-extrapolation
risk.

Building this live surfaced a second, unrelated real bug:
`shots_natural_key`'s UNIQUE CONSTRAINT included a nullable column
(`situation`), and Postgres never treats two NULLs as equal in a
unique constraint — `ON CONFLICT` silently failed to dedupe any shot
with `situation IS NULL`. La Liga has ~6.7% NULL-situation rows vs ~1%
for EPL/SERIE_A, so it took the brunt (1365 duplicate rows, 100% La
Liga, confirmed live — a single goal had landed 5 times under 5
different `shot_id`s). Fixed via
`sql/migrations/0037_fix_shots_null_situation_dedup.sql` before this
ADR's own work continued — unrelated to in-play specifically, but
found *because of* the in-play validation cross-checking reconstructed
scores against real final scores, exactly the kind of check that
catches this class of bug.

**Decision:** Build the backend only, no live UI yet (explicit
2026-09-30 direction — validate real output against real matches
before committing to any frontend work). `live_win_probability`
(`sql/migrations/0038_live_win_probability.sql`) is a new, separate
time series table — explicitly NOT the immutable predictions ledger
(ADR-002): it updates continuously through a live match (every ~60s),
while a prediction locks once, pre-kickoff, forever. Full history
retained (not latest-snapshot-only), same precedent as
`match_odds_history` — how win-probability moved during the match is
the actually interesting signal for a future live chart.

`scripts/poll_live_winprob.py` (new `futbol-live-winprob` CronJob,
every minute) gates on our own `matches` table *before* ever calling
the real API — a tick where nothing tracked could plausibly be live
right now is a near-zero-cost no-op, not a real API call, so running
every 60 seconds doesn't mean burning quota every 60 seconds.
Data source: `/fixtures?live=all` (one call covers every live fixture
across every league). Rolled out gradually — EPL and SERIE_A only for
now (both have deep, validated multi-season history); MLS (no
goal-minute data at all yet — `/fixtures/events` is the real candidate
source, not yet built) and LA_LIGA (validated but only for the single
season its `shots` table actually covers) come later.

**Update, same day:** the red-card adjustment moved from "stubbed at
1.0" to calibrated and live within hours of this ADR being written.
`scripts/experiment_redcard_calibration.py` backfilled real red-card
minutes (`/fixtures/events`) for every EPL/SERIE_A match with a
recorded red card, and compared the sent-off team's and their
opponent's actual remaining-time goals (`futbol.shots`) against
Dixon-Coles' unadjusted expectation. Real, consistent effect in both
leagues (EPL: down 0.475×, up 1.551×, n=145; SERIE_A: down 0.584×, up
1.850×, n=149) — large enough, and directionally consistent enough
across two independent leagues, to ship over the previous no-op,
despite being an in-sample-only check (see
`docs/EXPERIMENT_REGISTRY.md` for the full honest caveat: factors
weren't validated on a held-out red-card set, since neither league has
enough red-card matches yet to split one out). `apply_red_card()` in
`src/predictions/live_winprob.py` carries the calibrated constants;
`scripts/poll_live_winprob.py` now calls `/fixtures/events` once per
currently-live tracked fixture (not per tick) to detect a red card
before computing that fixture's probability.

Same in-passing discovery pattern as the shots-dedup bug above: while
backfilling `/fixtures/events`, found that `matches.external_ref` is a
single column overloaded by both Understat (`understat:<id>`) and
API-Football (`api-football:<id>`) — `link_fixture_ids()`'s `WHERE
external_ref IS NULL` guard means a historical EPL/SERIE_A/LA_LIGA
match (Understat-sourced first) can never also get an API-Football
ref. Confirmed NOT a production issue (every currently-*scheduled*
fixture already has the right ref — odds/injuries/final-pass are
unaffected), only blocks historical API-Football lookups for those 3
leagues. Worked around locally in the calibration script (team+date
matching, same technique `link_fixture_ids()` itself uses, just not
persisted); real fix (a separate `api_football_fixture_id` column)
logged as its own ticket, not urgent. See Todoist `6hfxhQccV87r4jcx`.

**Consequences:** The in-play feature didn't need the "different model
class" the ticket assumed — worth remembering the next time a ticket's
own framing turns out to be a bigger assumption than the evidence
supports. `live_win_probability` is the first continuously-updating
(non-locked) table in this schema's prediction-adjacent surface;
future similar features should follow its "separate time-series table,
not the ledger" pattern rather than trying to force a live value into
`predictions`. No live UI exists yet — that's explicitly a separate,
not-yet-made decision once the backend's real output has been checked
against real matches.

---

## ADR-012: 3-day slate window for NFL and soccer; stale slates are voided and regenerated

**Status:** Accepted (2026-10-02)

**Context:** The Dolphins' slate kept predicting De'Von Achane's rushing
yards after he tore his ACL in Week 3 and went on IR. The depth-chart
gate in `nfl_player_props.current_depth_chart()` was working: today's
nflverse chart no longer lists him. The real cause was timing. A manual
`generate_nfl_slate.py` run on 2026-09-06 slated 180 NFL games through
December in one batch. Every generator only fills fixtures with *no*
predictions, so the daily cron wrote 0 NFL rows from then on, and the
whole season stayed locked on the 2026-09-06 depth chart and form. The
receiving/receptions/anytime-TD markets added 2026-09-14 never reached
those games. Soccer had the same exposure by design: the cron slated
EPL/Serie A/La Liga 45 days out and MLS 21 days out. Injury and
suspension news only exists in the last few days before kickoff, so a
slate locked weeks earlier can never use it.

**Decision:**

1. **One 3-day window** (`predictions/slate_window.py`,
   `SLATE_WINDOW_DAYS = 3`) for NFL, EPL, Serie A, La Liga and MLS.
   It's enforced inside the generators, not only in `cronjobs.yaml`:
   `clamp_days_ahead()` caps any `--days`/`--days-ahead`, and
   `generate_for_fixture()` refuses a fixture outside the window
   whoever calls it. NBA (retired, ADR-009) is unchanged.
2. **"Already slated" means a live slate.** A fixture whose predictions
   are all voided counts as unslated (`NO_LIVE_PREDICTION_SQL`,
   `has_live_slate()`), so it gets regenerated.
3. **Regeneration runs under a new model version tag** (`v2` for
   `slate_generator_nfl` and `slate_generator_<league>`). The
   predictions natural key includes `model_version_id`, so a `v1`
   rerun would collide with the voided row and be dropped silently by
   `ON CONFLICT DO NOTHING`.
4. **Stale predictions are voided, never deleted or edited**
   (ADR-002/ADR-008). `scripts/void_stale_slates.py` adds one
   `prediction_grades` row per ungraded prediction locked more than 3
   days before kickoff, with `grader_version = 'stale-slate-void-1.0'`
   and a `void_reason`. When the subject player is known to be out,
   the reason names the absence first: NFL from the nflverse weekly
   roster (`RES`/`R01` → IR, and so on), soccer from a
   `player_injuries` row for that same match (cards → "suspended").
   Otherwise it says the slate was locked N days out, outside the
   window. Fixtures within 6 hours of kickoff are left alone, so none
   loses its slate before the regenerating run.
5. **Voiding before kickoff is allowed only under this rule:** a
   slate locked outside the published window, before any outcome
   could be known. That makes it a correction of *when* a claim was
   made, not a selective withdrawal of claims that look bad. It is
   applied to every stale row, not a hand-picked subset.
6. **Voids stay visible.** `get_slate()` ranks a voided row below a
   live one for the same key. A voided row nothing replaced still
   shows, with its reason, on the fixture and permalink pages.

**Consequences:** Predictions appear on the site at most about 3 days
before kickoff instead of weeks ahead. Every locked claim has seen the
last few days of injury, suspension and depth-chart news. The first
application voided every slate that ran weeks ahead (2026-10-02 dry
run: 5,690 predictions across 341 fixtures, including 92 rows for 4
NFL players on IR). That shows up publicly as void grades, not as a
rewritten history. Upstream lag still applies: the window only helps
as much as nflverse and API-Football keep their depth charts and
injury lists current.

---

## ADR-013: in-play remaining time uses an empirical goal-share curve, not 90 − minute

**Status:** Accepted (2026-10-02)

**Context:** ADR-011's in-play model scaled each team's remaining goal
expectation by `max(90 - minute, 1) / 90`, and its offline validation
stopped at 75'. Live, the poller reads API-Football's `status.elapsed`,
which caps at 90 for all of stoppage time, so the model always treated
stoppage as 1 minute. The first real series showed it: MLS match 4606
sat at 1-1 in stoppage with the draw at 0.966, and the home side
scored. Historically, 6.2% of EPL/SERIE_A goals come after minute 90;
the linear rule allows 1.1%.

**Decision:** For EPL, SERIE_A and LA_LIGA, remaining time is the
empirical share of a match's goals scored after the current elapsed
minute (`REMAINING_GOAL_SHARE`, pooled from 10,160 EPL + SERIE_A
Understat goals). It beat the linear rule on 2025-26 holdouts at every
checkpoint from 75' on, including La Liga, which never fed the curve
(89' log loss 0.476 → 0.341). MLS was first left on the linear rule
after a 33-match holdout; that sample turned out to be all goalless
games with no event data. After backfilling MLS 2025 events it scored
532 matches, 89' log loss 0.611 → 0.423, and was switched the same day
(2026-10-02). The
EPL/SERIE_A red-card factors were recalibrated against the new rule,
since the old ones were measured against the linear expectation and
had soaked up the same stoppage gap. Full numbers:
`docs/EXPERIMENT_REGISTRY.md`.

**Consequences:** Late-match probabilities stop collapsing toward
certainty before the final whistle. The live table
`futbol.live_win_probability` is outside the immutable ledger
(ADR-011), so earlier ticks stay as computed and new ticks use the new
rule.

---

## ADR-014: full-league Dixon-Coles fits use a small ridge penalty (reg=0.25)

**Status:** Accepted (2026-10-02)

**Context:** Production fit full leagues with `reg=0`. A team with zero
goals scored (or conceded) in its fit window, common for a promoted
side's first few games, then has an unbounded maximum-likelihood rating.
Live, 2026-27 promoted Coventry was priced at a 5e-8 win probability.
The degenerate-skip guard only drops outcomes that round to exactly 0 or
1, so the opposite side (~99.99%) still reached slates. The 2025-26
walk-forward reproduced it: log loss 14.9 (EPL) and 13.8 (La Liga) on
single matches.

**Decision:** `reg=0.25` for full leagues; small samples keep `reg=8`.
Both come from one helper, `models.dc_settings.dc_fit_settings()`, used
by the slate generator (and so the final pass and live poller) and by
`compute_team_ratings.py`, which must match the live fit. On the
2025-26 holdouts it lifted the lowest stated probability from ~3e-7 to
~3% and cut the worst log loss to 2.5–3.3, at no RPS cost. Soccer slate
model version moves to `v3`, so calibration can separate before and
after. Evidence and the tuning caveat: `docs/EXPERIMENT_REGISTRY.md`.

**Consequences:** Established teams barely move (they carry 100+
weighted matches against a 0.25 penalty). Promoted and very low-sample
teams are pulled toward league average until they have played enough
to stand on their own data. The degenerate-skip guard stays as a last
line of defense.

---

## ADR-009 addendum (2026-10-03): NBA stops generating predictions

ADR-009 retired NBA from further investment but left the shipped model
slating and grading. That's now ended: NBA is out of the product, because
a third sport with a frozen model muddies what the site claims to do.
`generate_nba_slate.py` is removed from `futbol-auto-slate` and
`nba_slate:2026-27` from the health check's expected jobs. NBA results
ingestion stays in `futbol-nightly-refresh` for now, because 1,944 NBA
2026-27 predictions were already locked (slated up to 45 days out)
before this decision. Whether they're graded as they come due or voided
before tip-off is still to be decided, and that decides whether the
ingestion step stays.

---

## ADR-015: per-provider match id columns (migration 0041)

**Status:** Accepted (2026-10-03)

**Context:** `matches.external_ref` held exactly one source's id
(`understat:…`, `api-football:…`, `nba:…`, `nflverse:…`). Historical
EPL/SERIE_A/LA_LIGA rows were created by Understat, so they could never
also carry an API-Football fixture id (`link_fixture_ids()` only wrote
where `external_ref IS NULL`). And loading Understat data onto rows
API-Football had created went wrong both ways: an exact kickoff match
kept the API-Football ref and dropped the shots, while a kickoff
mismatch created a duplicate match. The 2025-26 La Liga Understat load
had made 4 duplicates.

**Decision:** Add `matches.api_football_fixture_id` and
`matches.understat_game_id` (unique when set), filled from
`external_ref`, plus a trigger that keeps them filled whenever any
existing writer sets an exact `<provider>:<id>` ref. `external_ref` is
unchanged (NFL/NBA/WC still use it). Everything that needs an
API-Football id (odds, injuries, events, live poller, final pass,
`backfill_primary`'s lookup, `link_fixture_ids`) reads or writes the new
column. The 4 La Liga duplicates were resolved ADR-005-style: the
API-Football orphan gets `status = 'duplicate'` and a
`-superseded-by-<keeper>` ref (nothing deleted, no predictions
involved), and the Understat keeper takes over its fixture id.

**Consequences:** A match can now carry both providers' ids, which
unblocks the La Liga 2021–25 Understat shot backfill (linked onto
existing rows, never creating matches) and historical API-Football
lookups for EPL/SERIE_A/LA_LIGA.
