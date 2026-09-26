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
