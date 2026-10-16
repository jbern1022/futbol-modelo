# Adding a soccer league

Written from the Bundesliga rollout (phase 2 expansion, October 2026) and
meant to be corrected as the next leagues find what it missed. Everything
here was checked against the code at the time; where a step was not
exercised yet it says so. League-specific plans: Notion, "Phase 2 league
expansion plan".

A league touches about a dozen places (45 files mention `LA_LIGA`, not all
need edits). The order below keeps every step reversible until the last one.

## 0. Before writing code

1. **Baseline.** `python scripts/experiment_new_league_baseline.py --league-id <API id> --first-season 2021 --holdouts 2023 2024 2025`
   (about 6 API calls, no database). Log it in `docs/EXPERIMENT_REGISTRY.md`.
2. **Look at the API's round names** for the league (`/fixtures?league=<id>&season=<y>`).
   The Bundesliga lists its relegation play-off matches in the league feed;
   Liga MX has no round called "Regular Season" at all (`Apertura`,
   `Clausura`, `Apertura - Quarter-finals` ...). Decide the filter first.
3. **Club names.** Compare API-Football's names with Understat's. The API
   sometimes spells one club two ways for one id (Bundesliga: 4 clubs).
4. **Overlap with the database.** None of the Bundesliga clubs existed in
   `futbol.teams`; check by `api_football_id` and by name (`teams.name` is unique).
5. **Dry run the backfill read-only**: fixtures listed vs kept, clubs the
   alias table would create, Understat games linkable by teams and date
   (+-2 days) onto the planned matches.

## 1. Configuration (code only, no database writes)

| File | Change |
|---|---|
| `src/ingestion/api_football.py` | `LEAGUE_SEARCH`, `API_LEAGUE_IDS` (use the explicit id: the name search takes the first hit), `REGULAR_SEASON_ROUND_PREFIX` if the feed carries other rounds, `CROSS_YEAR_LEAGUES` if the season spans two years (label `2025-26`; otherwise the bare year), `NAME_ALIASES` for double spellings |
| `src/ingestion/loader.py` | `LEAGUES` (soccerdata key, only for Understat/FBref leagues) |
| `src/ingestion/entities.py` | `TEAM_SEED`: canonical name = the name `resolve_or_create_team_id` will create (`NAME_ALIASES.get(api_name, api_name)`), plus the Understat name. No FBref names without a live diff |
| `scripts/backfill_understat_shots.py`, `scripts/experiment_xg_blend.py` | add the league to `--league` choices |

Tests to copy: `tests/test_bundesliga_config.py`.

## 2. History backfill (writes to the production database)

**Route A is closed to new leagues (ADR-019): do not add a league on the Understat route.** Use route B.

Route A (Understat league): API-Football's primary backfill creates clubs,
matches, team stats and player rows; Understat shots and xG are linked onto
those matches afterwards (ADR-015). Route B (no Understat): the same API
backfill alone.

- One season at a time: `python -m ingestion.api_football backfill --league <CODE> --season <start year> --primary`.
  Cost is 1 fixture-list call plus 2 calls per finished match (team statistics, players):
  about 610 calls and 7 to 8 minutes for a 306-match season.
- **Backfill history seasons only at first.** `/v1/fixtures` has no league
  filter, so scheduled fixtures of the current season would appear on the
  live fixtures list before the web knows the league. Backfill the current
  season when the league is wired in.
- Load the API key from `~/.zshrc` in the same command; an old exported
  value fails on the first call (nothing is written when it does).
- After each season check: matches and finals, distinct fixture ids, clubs,
  team-stat rows (2 per match), score sanity, predictions on the league (0),
  and the global table deltas against a baseline taken before the first run.
  Yellow cards are null where a team had none.
- A restore point exists from the nightly backup (`~/futbol-modelo-backups`
  on docker-host, 03:15 UTC).
- Understat link: `python scripts/backfill_understat_shots.py --league <CODE> --seasons 2122 ... --dry-run`
  first (it needs the matches to exist), then without `--dry-run`.
  `soccerdata` downloads a prebuilt native TLS library on first use.

## 3. Validation (each gets a registry entry; pre-register what has a success rule)

Off by default for a new league. Do not add it to these sets until its entry passes:

| Switch | Where | Why it waits |
|---|---|---|
| `XG_BLEND_LEAGUES` | `src/models/xg_blend.py` | needs a pre-registered pooled test (fixed w=0.5, ADR-016) |
| `XG_FILL_LEAGUES` | `src/ingestion/api_football.py` | API xG for the live season needs a rescale factor from matches that have both sources |
| `RED_CARD_FACTORS` | `src/predictions/live_winprob.py` | needs goal-minute data (Understat shots or `match_events`) |
| `EMPIRICAL_REMAINING_LEAGUES` | same | stoppage-time share (ADR-013) per league |
| `PROPS_LEAGUES`, `PLAYER_PROPS_LEAGUES`, `CARDS_LEAGUES` | `scripts/generate_slate.py` | the props models train on rows **pooled across leagues**, so adding a league changes the other leagues' corners and shots models; it needs its own entry and a model-version bump |

Until then the league gets the goals-based markets only (1X2, BTTS, total
goals), which the baseline validates.

## 4. Wiring

- **Own CronJob for the nightly refresh**, not a step in `futbol-nightly-refresh`:
  that chain is joined with `&&`, so one failing backfill would stop
  `rebuild_features` and `compute_team_ratings`, and `futbol-auto-slate` waits on
  the latter. Schedule it before the main chain (11:30 UTC).
- Append the league at the **end** of the slate (after the NFL slate) and odds
  chains, so its failure cannot block the others.
- `ops/deploy.sh`: add a `patch_cronjob` line for every new CronJob (stale-`:latest` trap).
- `scripts/check_pipeline_health.py`: `EXPECTED_JOBS` and `SLATED_LEAGUES`.
- `scripts/compute_team_ratings.py`: `LEAGUES` (adds about two minutes to a 7-minute job).
- `api/petey_filter.py` `ALLOWED_LEAGUE_VALUES`; `api/main.py` standings description.
- Web: `fixture-list.tsx`, `lib/prediction-display.tsx` (badge colours), `standings/page.tsx`,
  `team-ratings/page.tsx`, `petey-widget.tsx`, `track-record/home-advantage-section.tsx`,
  `data-dictionary/page.tsx`, and the marketing copy in `web/messages/en.json` and `es.json`.
- Tests to copy: `tests/test_bundesliga_wiring.py`, which also guards that the switches in section 3 stay off.

## 5. Launch

1. `kubectl apply -f k8s/cronjobs.yaml` **before** the image patch (`apply` reverts out-of-band image pins).
2. Build and push the API and web images and the modelo image (kubectl is only on the Mac; builds run on docker-host).
3. Backfill the current season, then trigger the first refresh and slate by hand and read the logs.
4. Watch `pipeline_runs` for the new job names and the first graded predictions.
5. Every league starts its own evidence clock at zero (ADR-017); backfills and backtests do not advance it.

## Known gaps in this checklist

Not exercised yet: the Understat link and shot rows, the validation entries, the cron and web changes in production, and the final-pass and live-poller steps (left out of the first launch on purpose). National teams are a separate subsystem and are not covered here.
