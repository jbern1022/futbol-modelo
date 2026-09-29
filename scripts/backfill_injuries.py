"""
One-off historical injuries backfill (Todoist: "futbol-modelo:
lineup/injury news as a model feature", Phase 2). Unlike
backfill_referees.py, /injuries has no bulk-by-season equivalent --
referee arrives for free in the same /fixtures?league=&season= call
backfill() already makes, but injuries needs one real API call PER
FIXTURE (see src/ingestion/api_football.py's fetch_and_store_injuries).
Real rate-limit cost: expect this to take real wall-clock time across
4 leagues x several seasons, same sequential/resumable/append-log
discipline as scripts/run_historical_fbref_backfill.sh, not
backfill_referees.py's "one call per season" cheapness.

Idempotent (ON CONFLICT DO UPDATE in fetch_and_store_injuries) -- safe
to kill and re-run; already-fetched fixtures just get overwritten with
the same historical availability data, not duplicated.

    python scripts/backfill_injuries.py --league MLS
    python scripts/backfill_injuries.py --league EPL --seasons 2024-25 2025-26
"""
import argparse
import logging
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ingestion.api_football import _api_football_fixture_id, _session, fetch_and_store_injuries

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


def backfill_injuries_for_league(conn, session, league_code: str,
                                 season_labels: list[str] | None) -> tuple[int, int]:
    with conn.cursor() as cur:
        query = """SELECT m.match_id, m.external_ref FROM futbol.matches m
                   JOIN futbol.seasons s ON s.season_id = m.season_id
                   JOIN futbol.leagues l ON l.league_id = s.league_id
                   WHERE l.code = %s AND m.external_ref LIKE 'api-football:%%'"""
        params: list = [league_code]
        if season_labels:
            query += " AND s.label = ANY(%s)"
            params.append(season_labels)
        cur.execute(query, params)
        matches = cur.fetchall()

    # Committed every 20 fixtures (not one giant transaction) -- a
    # multi-thousand-fixture full-history run across 4 leagues is
    # exactly the kind of thing that gets killed partway through (rate
    # limit, network blip, a Ctrl-C), and re-running from scratch would
    # waste real API-Football quota re-fetching fixtures already stored.
    stored, skipped = 0, 0
    for i, (match_id, external_ref) in enumerate(matches, start=1):
        # Real data: a handful of external_ref values carry a
        # "-superseded-by-<id>" suffix from a past duplicate-match
        # cleanup (see CLAUDE.md/ADR-005) -- _api_football_fixture_id's
        # strict regex (same helper fetch_and_store_odds() already
        # relies on) returns None for those instead of a garbage int.
        fixture_id = _api_football_fixture_id(external_ref)
        if fixture_id is None:
            skipped += 1
            continue
        try:
            with conn.cursor() as cur:
                n = fetch_and_store_injuries(session, cur, fixture_id)
            stored += n
        except Exception:
            conn.rollback()
            log.warning("fixture %d (match_id %d) failed -- skipping, continuing",
                       fixture_id, match_id, exc_info=True)
            skipped += 1
            continue
        if i % 20 == 0:
            conn.commit()
            log.info("progress: %d/%d fixtures processed (%d records so far)",
                     i, len(matches), stored)
    conn.commit()
    return stored, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", action="append", required=True,
                    choices=["EPL", "SERIE_A", "MLS", "LA_LIGA"])
    ap.add_argument("--seasons", nargs="+", default=None,
                    help="Season labels to backfill, e.g. 2024-25 2025-26 "
                         "(MLS uses bare years, e.g. 2025 2026). "
                         "Defaults to every season already linked to API-Football.")
    args = ap.parse_args()

    session = _session()
    conn = psycopg2.connect(DSN)
    total_stored = total_skipped = 0
    try:
        for league_code in args.league:
            stored, skipped = backfill_injuries_for_league(
                conn, session, league_code, args.seasons)
            total_stored += stored
            total_skipped += skipped
            log.info("%s: %d injury records stored, %d fixtures skipped",
                     league_code, stored, skipped)
    finally:
        conn.close()
    log.info("done: %d total injury records stored, %d fixtures skipped",
             total_stored, total_skipped)


if __name__ == "__main__":
    main()
