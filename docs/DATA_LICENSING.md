# Futbol Modelo — Data-Source & Licensing Register

**Status:** Draft — inventory compiled from the actual ingestion code
and its header comments (`src/ingestion/*.py`) as of 2026-09-26, not
guessed. Flagged gaps below need a real terms-of-service read before
this register can be called complete — see "Open gaps."

## Inventory

| Source | Used for | Access | Update frequency | Attribution required? | Redistribution/commercial-use notes |
|---|---|---|---|---|---|
| **Understat** | Soccer match results + shot-level xG/player stats (EPL/Serie A/La Liga history) | Scraped, no API key (`src/ingestion/loader.py`, `load_understat`) | Backfill + ongoing | Not confirmed — **gap, see below** | Not confirmed — **gap, see below** |
| **FBref** | Soccer match/player stats, World Cup knockout data (`load_fbref`) | Scraped, no API key | Backfill + ongoing | Not confirmed — **gap, see below** | Not confirmed — **gap, see below** |
| **API-Football** | Corners, cards, saves, shots-on-target, possession (soccer); live odds (`match_odds_history`) via `odds` mode | Paid API, key required (`src/ingestion/api_football.py`) | Ongoing (intraday odds, daily/nightly stats) | Per API-Football's own ToS — **not re-read for this register, see below** | Paid-tier commercial terms apply; ADR-004 already documents the operational risk of depending on this being the *primary* MLS data path with no free fallback |
| **nflverse** (via `nfl_data_py`) | NFL schedule, scores, real closing market lines, player box scores | Free, no API key, no rate limit — stated directly in the ingestion header (`src/ingestion/nfl_data.py`) | Season backfill + weekly | **Yes — CC-BY, per the code's own header comment** | CC-BY permits reuse with attribution; this project should carry that attribution publicly (see "Open gaps") |
| **nba_api** (wraps stats.nba.com) | NBA schedule, results, player box scores | Free, no API key (`src/ingestion/nba_data.py`) | Season backfill + ongoing | Not confirmed — **gap, see below**. `nba_api` is a third-party wrapper around an undocumented-for-third-party-use NBA.com endpoint, not an official NBA data product | Not confirmed — **gap, see below**; no official commercial-use grant is known to exist for this endpoint |
| **StatsBomb open data** | Researched for MLS custom xG (not currently ingested — see the deferred "Phase 4: MLS custom xG" ticket) | Free, public GitHub release (2023 MLS season only, static) | One-time historical, not a live feed | **Yes — "Data provided by StatsBomb" attribution required**, per the deferred ticket's own research notes | Free for non-commercial/research use per StatsBomb's stated terms; **the live public site is arguably a commercial-adjacent use** — worth a real terms re-read before this data is ever wired in, not just before its non-commercial research use |

## Coverage gaps (by design, not oversight)

- **Player props (`PLAYER_GOALS`, `PLAYER_SAVES`):** soccer-only,
  MLS-only today — the only league with `player_match_stats`
  populated (La Liga's historical FBref backfill was deliberately
  skipped; EPL/Serie A shipped 2026-09-21). See
  `docs/RESEARCH_PROTOCOL.md` for how new markets get validated before
  shipping.
- **NFL/NBA player props:** no real market line exists for individual
  player props from either free source used here — both self-generate
  candidate lines around a prediction rather than pricing against a
  real book, stated explicitly in `README.md` and `CLAIMS.md`.
- **World Cup knockout:** FBref-sourced, historical only, feeds
  `knockout_extension()` in `src/models/dixon_coles.py`.

## Rate limits (as coded, not necessarily as published)

- **API-Football:** paid-tier rate limits apply; ADR-004 documents the
  real operational cost of MLS depending on this tier being active
  with no coded fallback.
- **nflverse/nba_api:** no rate limit encountered or coded around, per
  the ingestion headers — but "no rate limit observed" is not the same
  claim as "no rate limit exists," see gaps below.

## Open gaps — need a real ToS/attribution read, not assumed

This register is only as honest as `CLAIMS.md`'s own three-tier
standard demands, so these are stated as gaps rather than papered
over:

1. **Understat and FBref scraping terms** were never confirmed against
   either site's actual terms of service in this session — the code
   comments describe *how* data is fetched, not *under what license*.
   Both are widely scraped by the public soccer-analytics community,
   but "commonly done" is not the same as "confirmed permitted,"
   especially for a site that publishes derived predictions publicly.
2. **nba_api / stats.nba.com terms** — same gap. `nba_api` is a
   well-known open-source wrapper, but the underlying endpoint has no
   published third-party data license; the project has not stated
   anywhere it accepted a specific risk here.
3. **nflverse attribution is not yet visible on the live site** — the
   code header correctly identifies CC-BY, but `README.md`'s current
   text does not carry a public attribution line for it. This is a
   real, cheap gap to close (add an attribution line to the site
   footer or `README.md`), unlike gaps 1–2 which need actual research.
4. **API-Football's redistribution terms** for derived predictions
   (as opposed to raw data) were not re-read for this register.

None of these gaps block current operation — they're flagged because
"document the data-source register" was the actual ask, and an honest
register says where it doesn't yet have an answer rather than filling
the cell with a guess.

## Related documents

- `docs/RESEARCH_CHARTER.md`, `docs/RESEARCH_PROTOCOL.md` — this
  register is what those documents' data-availability claims rest on.
- ADR-004 in `docs/DECISIONS.md` — the API-Football dependency risk.
