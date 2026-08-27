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
