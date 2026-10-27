# Bundesliga launch checklist (2026-10-27)

Status check for Todoist `6hmV7JcG2qFfXQvf`. Nothing here has been run. Each production step below
needs its own explicit go-ahead (owner resolution 2026-10-26: separate authorization per step).

## State on 2026-10-27 (read-only checks)

| Item | Finding |
|---|---|
| Code | Merged to `main` (`feat/bundesliga-props`, e1c0ffb); live image `62173d7` contains it. |
| DB | 1,530 history matches (2021-22 to 2025-26). **No 2026-27 matches, no predictions.** |
| API-Football, league 78, season 2026 | 306 fixtures, 2026-08-28 to 2027-05-22: **63 finished, 243 not started** (7 rounds played). |
| Teams | 18; 2 are not in the DB (SC Paderborn 07, SV Elversberg). `backfill_primary` creates missing teams via `resolve_or_create_team_id`. |
| API quota | Pro plan, 7,500/day, 1,881 used when checked; plan ends 2026-12-27 (renewal ticket `6hm4XP33rwJfGFVf`). |
| Cluster | 8 CronJobs live, **no `futbol-nightly-refresh-bundesliga`**. The manifest has four Bundesliga touchpoints: its own nightly CronJob (11:30 UTC, `backfill --league BUNDESLIGA --season 2026 --primary`), a step in `futbol-auto-slate` (line 191) and two in the odds jobs (lines 290, 336). |
| Health check | `EXPECTED_JOBS` already lists `nightly_refresh:BUNDESLIGA`, `auto_slate:BUNDESLIGA`, `odds:BUNDESLIGA`. See the warning below. |

## Warning: the health check will alert before launch

Image `62173d7` is live on `futbol-pipeline-health`. Its next run (13:15 UTC) will report the three Bundesliga jobs
as stale (`auto_slate` and `odds` never succeeded; `nightly_refresh` last succeeded 2026-10-14) and post a
high-priority ntfy alert. It is a false alarm until the launch. Mitigation without a rebuild: patch only that
CronJob back to `:1641002`, whose list has no Bundesliga jobs; re-patch to the current image at launch.

## Steps (each needs a go-ahead)

1. **Backfill 2026-27.** The nightly CronJob's own command is the backfill (one fixtures call plus per-finished-match
   statistics calls, roughly 63+ calls for the 63 finished matches). It can be run once by hand before the CronJob exists:
   `python -m ingestion.api_football backfill --league BUNDESLIGA --season 2026 --primary` (writes prod).
2. **Apply the CronJobs.** `kubectl apply -f k8s/cronjobs.yaml` changes more than the Bundesliga: check `kubectl diff`
   first, and apply objects one at a time (see the deploy-topology notes). Then patch images (apply resets them to `:latest`).
3. **Verify.** New CronJob present; `nightly_refresh:BUNDESLIGA` success; health check green.
4. **Live win-prob poller.** Separate and last, separate authorization.

Do steps 1 and 2 together: once 2026-27 rows exist, their scheduled fixtures show on the live list with no predictions
until the slate wiring runs.

## Timing

Slates lock 3 days before kickoff (ADR-012). Per the ticket's API calendar, round 8 is Oct 30 to Nov 1 and round 9 Nov 6 to 8
(dates after round 11 are placeholders; recheck). `futbol-auto-slate` runs 12:15 UTC and the Bundesliga nightly 11:30 UTC, so
the Bundesliga rows and CronJobs must be live **before 11:30 UTC on Oct 28** for the Oct 28 slate to cover early round-8
fixtures; otherwise the first graded round is round 9.

## Release criteria (owner-approved 2026-10-26)

Passing CI, verified identities, licensing, source coverage, rollback, grading. Open items from the tickets:
Understat licensing (`6hmV7JJxQpG2Wqhf`), FBref terms (`6hmVCJQVqgwHfP67`), API-Football terms (`6hmV7JRq3XqPHqM7`),
Bundesliga shots on target (`6hmV7JPR2PMPHcG7`, recommended off).

## Rollback

Delete the Bundesliga CronJob (`kubectl delete cronjob futbol-nightly-refresh-bundesliga`) and re-apply the previous
`futbol-auto-slate` and odds objects. Predictions are insert-only: Bundesliga predictions already written cannot be edited,
only voided with a new grade row.
