# Claims

Every assertion in the README and on the live site, mapped to what
actually checks it. Three honest categories, not two — "tested" is not
the same as "true," and pretending otherwise is exactly the kind of
gap this file exists to close:

- **Tested** — an automated test asserts this directly.
- **Live-verified** — checked by hand against the real, running system
  (this session or a prior one), no standing test.
- **Code path only** — the code that would make this true exists and
  was read, but nothing automated or manual has actually confirmed it
  fires correctly. The honest gap.

This file will drift the moment code changes without an update here —
treat a stale entry as a bug, same as any other.

## The ledger

| Claim | Enforced by | Status |
|---|---|---|
| `predictions` is INSERT-only; UPDATE/DELETE rejected | `forbid_prediction_mutation()` trigger, `sql/schema.sql` | **Tested** — `tests/test_predictions_immutable.py::test_update_is_rejected`, `test_delete_is_rejected` |
| A prediction locked at or after kickoff is rejected | `enforce_pre_kickoff()` trigger, `sql/schema.sql` | **Tested** — `tests/test_predictions_immutable.py::test_insert_locked_at_or_after_kickoff_is_rejected` |
| A prediction locked before kickoff succeeds (sanity check on the above) | same trigger | **Tested** — `tests/test_predictions_immutable.py::test_insert_locked_before_kickoff_succeeds` |
| Corrections are new `void` grades, never edits to the original row | `prediction_grades` schema + convention, e.g. `sql/void_duplicate_match_predictions.sql` | **Tested** — `forbid_grade_mutation()` trigger, `sql/migrations/0007_lock_prediction_grades.sql`, rejects raw `UPDATE`/`DELETE`; asserted by `tests/test_grades_immutable.py::test_grade_update_is_rejected`, `test_grade_delete_is_rejected` |
| `predictions.context` NaN values are sanitized to `null`, not left invalid | `_sanitize_context()`, `src/predictions/generator.py` | **Tested** — `tests/test_prediction_context.py`, via a commit-suppressing connection wrapper so `persist_slate()`'s internal `conn.commit()` no longer leaves a permanent test row in the live ledger |
| A fixture that somehow gets slated twice can't double-count in the published stats | `v_graded_predictions` dedup view, `sql/migrations/0003_dedupe_scorecard_views.sql` | **Live-verified** — 2026-08-27/28, real incident (match 4456): scorecard/calibration totals confirmed to drop by exactly the known duplicate count, raw ledger rows confirmed unchanged |

## The models

| Claim | Enforced by | Status |
|---|---|---|
| Dixon-Coles, time-decayed, one scoreline distribution drives 1X2/totals/BTTS | `src/models/dixon_coles.py` | **Tested** — `tests/test_dixon_coles_invariants.py` (property-based) |
| Props models are LightGBM, Poisson objective | `src/models/props.py` | **Code path only** — no test asserts the objective/library choice itself, only downstream behavior |
| Isotonic calibration is fit on out-of-fold predictions only, never on the model's own training folds | `props.py`'s `fit_props_model` | **Live-verified** — corners and SOT retrains this session confirmed real logloss improvement (+0.03984 for SOT) after the fix landed; not re-verified per retrain going forward |
| Rolling features (`team_match_features`) never leak future information into a match's own row | `sql/features.sql`, as-of joins | **Tested** — `tests/test_features_no_leakage.py` |
| Player markets are MLS-only (the only league with `player_match_stats` populated) | `PROPS_LEAGUES` in `scripts/generate_slate.py` | **Code path only** — true as written, no test pins this list |

## The pipeline

| Claim | Enforced by | Status |
|---|---|---|
| Every real cron run is tracked (status, rows written, failure traceback) | `src/ops/pipeline_run.py`, `futbol.pipeline_runs` | **Live-verified** — repeatedly, this session (API-Football recovery, features-rebuild rollout) |
| `team_match_features` is rebuilt after every ingestion batch | `scripts/rebuild_features.py`, last step of `futbol-nightly-refresh` | **Live-verified** 2026-08-28 — triggered a real run, confirmed the rebuild step executed and reported correct row counts after ingestion |
| One bad fixture can't take an entire `auto_slate` batch (or the next league) down with it | per-fixture try/except in `scripts/auto_slate.py` | **Live-verified** 2026-08-28 — the exact real fixture that previously crashed the batch (Coventry vs Hull City) now produces a partial, valid slate instead |
| The freshness footer ("Predictions last generated Xh ago") reflects reality, not a cached lie | `GET /v1/pipeline-status`, `web/app/footer.tsx` | **Live-verified** — checked against real `pipeline_runs` rows this session |
| Real bookmaker odds are stored with the bookmaker's vig removed (no-vig probability), MLS only | `fetch_and_store_odds()`, `src/ingestion/api_football.py`, `match_odds` table | **Code path only** — `normalize_match_winner_odds()`/`remove_overround()` (the math) and `match_odds`'s upsert-in-place behavior are directly tested against the live DB, but `fetch_and_store_odds()` itself has never been run against the real API (no automated test, same as `backfill()`/`backfill_primary()`; costs real API quota, not run this session) |

## Petey (LLM safety)

See `docs/adr/petey-decisions.md` for the full 11-ADR trail this table summarizes.

| Claim | Enforced by | Status |
|---|---|---|
| Ollama never writes SQL or sees raw rows/schema | `ask_petey()`/`ask_team_form()` only ever pass a pre-computed aggregate into the prompt, `api/main.py` | **Code path only** — true by construction (the code has no SQL-generation path for Ollama at all), but nothing automated asserts this stays true as the file grows |
| The default ("accuracy") mode filters unsupported judgment words from the LLM's output | `_contains_unsupported_judgment()`, called in both `ask_petey()` and `ask_team_form()` | **Tested via live verification only** — 2026-08-27, found and fixed the exact gap where `ask_petey()` didn't call this (a real "fix built, never wired into the real path" incident); no automated test pins either call site today. The still-open "Petey evaluation harness" ticket is the real fix for this gap. |
| A failed/slow Ollama call still returns a real, honest number (never a raw 500 or a hang) | `OLLAMA_TIMEOUT_SECONDS` + deterministic fallback templates in both endpoints | **Code path only** |

## Infrastructure

| Claim | Enforced by | Status |
|---|---|---|
| Deploys are `imagePullPolicy: Never` everywhere, no registry pull | `k8s/webapp.yaml`, `k8s/cronjobs.yaml` | **Live-verified** — every deploy this session |
| A CronJob's live spec matches what's in `k8s/cronjobs.yaml` | manual `kubectl apply` discipline | **Code path only, and a real gap** — 2026-08-28, rebuilt and imported a new image expecting a new CronJob step to run, and it silently didn't, because the live CronJob *object* still had the old command; the image alone was never enough. No drift-detection exists for this today. |
| Nightly Postgres backups exist, off the source LXC, and are actually restorable | `ops/backup-futbol-db.sh`, `ops/README.md` | **Live-verified** 2026-08-27 — ran the backup for real, then did a full restore drill into a throwaway database and confirmed every table's row count matched the live DB exactly |
