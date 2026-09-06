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
| NFL power ratings (margin + total via ridge regression) predict MONEYLINE/SPREAD/TOTAL_POINTS against real market lines | `src/models/nfl_power_ratings.py`, `scripts/generate_nfl_slate.py` | **Live-verified** 2026-09-06 — 17 real Week 1 2026 fixtures slated, 102 predictions written into the ledger against nflverse's real, free market lines. **Explicitly NOT calibrated**: probabilities come from a Normal-approximation on the model's own residual std dev, not isotonic-on-out-of-fold like the soccer props models — there's no graded NFL history yet to calibrate against before a single 2026 game has been played. Revisit once a real number of weeks are graded. |
| NFL player props (QB passing yards, RB rushing yards) predict against a recency-weighted rolling average, gated by the real current depth chart | `src/models/nfl_player_props.py`, `scripts/generate_nfl_slate.py` | **Live-verified** 2026-09-06 — 2,617 real PLAYER_PASS_YARDS/PLAYER_RUSH_YARDS predictions written into the ledger across 49 real upcoming fixtures, checked in a local browser. No real market line exists for individual player props (nfl_data_py's schedule data covers game-level lines only) — same self-generated-candidate-line treatment as NBA's player points. WHO gets a prediction is decided by nflverse's actual published depth chart (QB1, RB1/RB2), not by rolling-stat presence alone — a real design choice made explicitly to avoid the failure mode where a flat history window keeps predicting an injured/benched player for several games after a real role change. Two real bugs found and fixed before shipping: (1) nfl_data_py returns a completely different column schema for the live/current season's depth chart than for a completed season's archived one — verified directly rather than assumed; (2) the live schema's snapshot rows repeat every past scrape timestamp in the same dataframe (300+ duplicate rows per team/position before filtering to the latest `dt`). **Explicitly NOT calibrated**, same honest gap as every other new-sport model this session. |
| NBA power ratings predict TOTAL_POINTS and PLAYER_POINTS against self-generated candidate lines | `src/models/nba_power_ratings.py`, `src/models/nba_player_points.py`, `scripts/generate_nba_slate.py` | **Live-verified** 2026-09-06 — fit on 1230 real 2025-26 games; live-verified against real fixtures across a 100-day window, 500+ TOTAL_POINTS and 500+ PLAYER_POINTS predictions written into the ledger, checked in a local browser. No moneyline/spread for NBA in this vertical slice (by design). Neither market has a real line to predict against (nba_api carries no bookmaker data) — candidate lines are spaced around a prediction (team total, or a player's own rolling scoring average) and only published when genuinely confident (same PROPS_OVER_BAND/PROPS_UNDER_BAND thresholds as soccer's corners/SOT). Real bug found and fixed before shipping: the player-roster lookup used a 21-*day* lookback window, which is empty at the start of every season (the prior season ends in June, the new one starts in October) — rewritten to a 15-*game* lookback instead, which correctly reaches back across the off-season gap. **Explicitly NOT calibrated**, same honest gap as the NFL model. |

## The pipeline

| Claim | Enforced by | Status |
|---|---|---|
| Every real cron run is tracked (status, rows written, failure traceback) | `src/ops/pipeline_run.py`, `futbol.pipeline_runs` | **Live-verified** — repeatedly, this session (API-Football recovery, features-rebuild rollout) |
| `team_match_features` is rebuilt after every ingestion batch | `scripts/rebuild_features.py`, last step of `futbol-nightly-refresh` | **Live-verified** 2026-08-28 — triggered a real run, confirmed the rebuild step executed and reported correct row counts after ingestion |
| One bad fixture can't take an entire `auto_slate` batch (or the next league) down with it | per-fixture try/except in `scripts/auto_slate.py` | **Live-verified** 2026-08-28 — the exact real fixture that previously crashed the batch (Coventry vs Hull City) now produces a partial, valid slate instead |
| The freshness footer ("Predictions last generated Xh ago") reflects reality, not a cached lie | `GET /v1/pipeline-status`, `web/app/footer.tsx` | **Live-verified** — checked against real `pipeline_runs` rows this session |
| Real bookmaker odds are stored with the bookmaker's vig removed (no-vig probability) — MLS, EPL, Serie A | `fetch_and_store_odds()`, `link_fixture_ids()`, `src/ingestion/api_football.py`, `match_odds` table | **Live-verified** 2026-09-05 — ran `fetch_and_store_odds()` against the real API-Football endpoint for all three leagues: MLS 102 rows/7 fixtures, EPL 144 rows/8 fixtures, Serie A 174 rows/10 fixtures, confirmed via direct query against `match_odds`. EPL/Serie A matches (created from Understat/FBref, not API-Football) already carried an `api-football:<id>` `external_ref` from an earlier run, so `link_fixture_ids()` reported 380/380 already-linked for both — the new function is exercised and correct (0 relinked, no clobbering), just not the thing that unblocked these two leagues. La Liga not yet linked (no 2026-27 season row in `seasons` yet). |
| The Track Record page shows the model's stated probability against the real no-vig market probability | `v_market_comparison` (`sql/migrations/0011_market_comparison_view.sql`), `GET /v1/odds-comparison`, `web/app/track-record/market-comparison-section.tsx` | **Live-verified** 2026-09-05 — checked the view directly against the live DB and the rendered page in a local browser: 21 real rows spanning MLS/EPL/Serie A, including a genuine 63.8-point divergence on Hull City vs Aston Villa (model 87.1% home win vs. market 23.3%). Not gated on grading — today's rows are pre-game estimate vs. pre-game estimate; the comparison for already-graded matches will appear here too once enough time passes, since `match_odds` rows aren't deleted after kickoff. |

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
