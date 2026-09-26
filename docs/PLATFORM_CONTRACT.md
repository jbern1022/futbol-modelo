# Futbol Modelo — Cross-Sport Platform Architecture Contract

**Status:** Draft — documents what the shared platform already
enforces today, plus the versioning/API/track-record policy that
extends it. Not yet reviewed by the project owner.

This is the contract every sport (soccer, NFL, NBA, and any future
sport) is held to. Where the contract is already enforced by real
schema/code, that's stated explicitly — this document does not invent
new mechanisms where the existing ones already do the job.

## Shared prediction ledger

**Already enforced, not proposed:**

- `predictions` is INSERT-only; a trigger (`forbid_prediction_mutation()`)
  rejects UPDATE/DELETE (ADR-002).
- A second trigger (`enforce_pre_kickoff()`) rejects any prediction
  locked at or after kickoff.
- Every sport writes into the *same* `predictions` table — there is no
  per-sport ledger. `market` is a single CHECK-constrained column
  covering soccer (`1X2`, `BTTS`, `TOTAL_GOALS`, `CORNERS`, `SOT`,
  `CARDS`, `PLAYER_GOALS`, `PLAYER_SAVES`), NFL (`MONEYLINE`,
  `SPREAD`, `TOTAL_POINTS`, `PLAYER_PASS_YARDS`, `PLAYER_RUSH_YARDS`,
  …), and NBA (`TOTAL_POINTS`, `PLAYER_POINTS`) side by side (see
  `sql/schema.sql`).

## Event schema

**Already enforced:** `matches` is the shared fact table for every
sport — same columns, same `external_ref`-first identity resolution
(ADR-005) regardless of sport. A new sport does not get its own
matches table; it gets new rows in the existing one plus new
`ingestion/` loaders (`nfl_data.py`, `nba_data.py` follow the same
loader shape as soccer's `loader.py`/`api_football.py`).

## Model registry

**Already enforced:** `model_versions` (see `sql/schema.sql`) is
sport-agnostic — `model_name` (e.g. `'dixon_coles'`,
`'nfl_power_ratings'`, `'nba_power_ratings'`), `version_tag`,
`trained_at`, `training_window`, `params`, `train_metrics`. Every
prediction row references a `model_version_id`, so "which model
version produced this claim" is always a join away, for any sport, no
exceptions.

## Grading pipeline

**Already enforced:** `prediction_grades` is append-only
(`forbid_grade_mutation()`, `sql/migrations/0007_lock_prediction_grades.sql`),
shared across sports. A correction is a new `void` grade row, never an
edit — the same rule ADR-002 states for the ledger itself applies
identically whether the graded prediction was a soccer 1X2 or an NFL
SPREAD.

## Calibration views

**Already enforced:** `v_calibration` and `v_season_scorecard`
(`sql/schema.sql`) are segmented by market *and* league/sport, feeding
the Track Record page for every sport from the same two views — no
per-sport calibration page or separate calculation path.

## Methodology versioning

**Policy, extending what's already true of the schema:** a change to
how a market is modeled, calibrated, or graded (a "methodology
change," distinct from a routine model retrain) gets:

1. A `model_versions` row, same as any retrain (already enforced).
2. An ADR in `docs/DECISIONS.md` if the change is architectural (the
   existing convention — ADR-003's isotonic-calibration decision is
   exactly this kind of change).
3. An entry in `docs/EXPERIMENT_REGISTRY.md` if it started as a
   hypothesis under this protocol, whether or not it shipped.

## API contracts

`api/main.py` (FastAPI, read-only DB role) is the single public
surface for every sport's predictions, grades, and calibration data —
no sport gets a parallel API. `GET /v1/pipeline-status`
(`src/ops/pipeline_run.py`) already reports per-cron-run health across
every sport's ingestion/slate/grade jobs from one endpoint. New sports
extend existing endpoints' response shapes (new `market`/`league`
values), not new endpoints, unless a genuinely new resource type is
introduced.

## Public track record

The Track Record page (frontend, backed by `v_season_scorecard`/
`v_calibration`) is the single public accounting surface for every
sport. A sport with an honest "not yet calibrated" status (NFL, NBA,
currently) is shown as such, not hidden — this mirrors `CLAIMS.md`'s
"three honest categories, not two" discipline applied to the public
site itself, not just internal documentation.

## What is explicitly sport-specific (not shared)

- The model class itself: Dixon-Coles Poisson (soccer) vs. ridge
  regression power ratings (NFL, NBA) — ADR-001 already documents why
  a single generic classifier wasn't chosen even within soccer; the
  same reasoning extends across sports (NFL's multimodal, 3/7-point
  clustered margin distribution is exactly why Dixon-Coles' Poisson
  machinery doesn't transfer, per `README.md`).
- Whether a real market line exists to predict against (NFL
  MONEYLINE/SPREAD have one via nflverse; NBA totals/player points and
  NFL player props self-generate candidate lines because no market
  line exists — see `docs/DATA_LICENSING.md`).
- Calibration status itself (soccer's mature markets are calibrated;
  NFL/NBA are not yet, honestly, per `docs/RESEARCH_PROTOCOL.md`).

## Related documents

- `docs/RESEARCH_CHARTER.md` — why this platform exists.
- `docs/RESEARCH_PROTOCOL.md` — the evaluation rules this contract's
  data feeds.
- `docs/DECISIONS.md` — ADR-002, ADR-003, ADR-005 are the specific
  accepted decisions this contract documents as already-enforced;
  ADR-008 extends ADR-002 with explicit publication/correction rules.
