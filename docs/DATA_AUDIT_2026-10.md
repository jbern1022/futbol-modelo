# Forecast timing, storage and source coverage audit (2026-10-03)

Closes Todoist `6hf57M9QXQFFRhj7` ("Audit soccer forecast timing, source
coverage, and SQL storage headroom"). Every number below was measured
against the live systems on 2026-10-03.

## Forecast timing — resolved by ADR-012

The "morning pipeline vs. 21–45 day slate" discrepancy the ticket asked
about was real: the cron slated EPL/SERIE_A/LA_LIGA 45 days out and MLS
21 days out, and a manual run had slated the NFL through December. Since
ADR-012 every NFL/soccer slate locks at most 3 days before kickoff
(enforced in code), and `check_pipeline_health.py` alerts on missing or
out-of-window slates. NBA no longer slates (ADR-009 addendum).

## Storage and backups

| Item | Measured | Headroom |
|---|---|---|
| `futbol` database | 181 MB | — |
| Postgres LXC (VMID 210) disk | 1.2 GB used of 32 GB (4%) | ~29 GB free |
| Largest tables | `player_injury_features` 56 MB, `shots` 28 MB, `player_match_features` 22 MB, `player_match_stats` 20 MB | — |
| Nightly backups (`~/futbol-modelo-backups/` on docker-host, 03:15 UTC, 14 kept) | ~13.8 MB per dump, 136 MB total | docker-host: 40 GB free of 116 GB |

**Growth.** Match-driven data is tiny (a full season across four soccer
leagues is a few tens of MB including shots and player stats). The one
unbounded writer is `pipeline_runs`: the per-minute live poller logs
5,760 rows a day (4 leagues × 1,440), about 2M rows / ~400 MB a year.
`live_win_probability` itself only writes while matches are live (~110
rows a match, ~200k a season).

**Retention recommendation.** Keep all match, prediction, grade and
feature data (3–5+ seasons fit easily; nothing needs pruning for
years). Add a retention rule for `pipeline_runs` rows from
`live_winprob:*` older than 30 days. They're health telemetry, not
evidence. Every other table: no retention needed.

## Source coverage (finished matches, % of matches with the data)

| League | Seasons | Corners/shots | xG | Understat shots | Events | Player stats | Injuries | Odds | Referee |
|---|---|---|---|---|---|---|---|---|---|
| EPL | 2021-22 – 2025-26 | 100 | 100 | 100 | 0 | **100 / 100 / 0 / 0 / 100** | 0 | 0 | 100 |
| EPL | 2026-27 | 100 | 100¹ | 0 | 0 | 100 | 0 | 36 | 100 |
| SERIE_A | 2021-22 – 2025-26 | 100 | 100 | 100 | 0 | **0** | 0 | 0 | 100 |
| SERIE_A | 2026-27 | 100 | 100¹ | 0 | 0 | 100 | 0 | 40 | 100 |
| LA_LIGA | 2021-22 – 2025-26 | 100 | 100² | 100² | 0 | 99–100 | 0 | 0 | 0 |
| LA_LIGA | 2026-27 | 100 | 100¹ | 0 | 0 | 100 | 0 | 0 | 0 |
| MLS | 2021 – 2024 | 100 | — | — | 0 | 100 | 0 | 0 | 0 |
| MLS | 2025 | 100 | — | — | 100³ | 100 | 0 | 0 | 0 |
| MLS | 2026 | 100 | — | — | 100 | 99 | 100 | 9 | 0 |

¹ API-Football `expected_goals`, rescaled to the Understat scale.
² La Liga 2021-25 Understat backfill, 2026-10-03 (ADR-015).
³ Backfilled 2026-10-02 for the in-play experiments.

**Gaps that matter:**

1. **Player match stats: EPL 2023-24 and 2024-25, and all of SERIE_A
   history, are empty.** PLAYER_GOALS / PLAYER_SAVES train on what's
   there, so Serie A's player props have no history behind them.
   Fillable now from API-Football `/fixtures/players`: every historical
   EPL/SERIE_A match carries an `api_football_fixture_id` since ADR-015.
   About 2,660 calls, within one day's quota.
2. **No Understat shots for 2026-27.** Understat was a one-off historical
   load. Live features use API-Football xG instead. Only shot-level
   research (custom xG, shot-based in-play validation) is affected.
3. **Match events exist only for MLS.** The live poller now stores them
   for every league going forward. History is fillable the same way
   (one call per match).
4. **Referee is missing for La Liga and MLS.** Harmless today, since
   CARDS is EPL/SERIE_A only.

## API usage, cost and licensing

- **API-Football:** Pro plan, 7,500 calls/day. 2,800 used on 2026-10-03,
  a heavy backfill day. Steady state is the nightly refresh plus odds,
  injuries and the live poller (one `/fixtures` call per league-minute
  when something could be live, plus `/fixtures/events` per live match).
  **The subscription ends 2026-12-27.** It's the primary MLS source
  (ADR-004) and the only current-season source for every soccer league,
  so a lapse stops the soccer pipeline.
- **Understat / FBref:** still scraped without confirmed terms
  (`docs/DATA_LICENSING.md`, open gap 1). The 2026-10-03 La Liga backfill
  extended existing historical use to one more league; nothing scrapes
  Understat on a schedule.
- **nflverse:** CC-BY, attribution already on the site.

## Forecast horizons

| Market group | Locks | Refresh |
|---|---|---|
| NFL + soccer slates | ≤ 3 days before kickoff (ADR-012) | none (immutable) |
| Soccer PLAYER_GOALS / PLAYER_SAVES | final pass ≤ 2 h before kickoff (ADR-010) | lineup-confirmed second prediction |
| In-play win probability | every ~60 s while live (ADR-011/013) | not part of the ledger |
