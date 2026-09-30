"""
One-off historical match-events backfill -- the MLS equivalent of the
Understat shot-level history EPL/SERIE_A/LA_LIGA already have (zero
MLS coverage there). Built to unblock MLS in-play win-probability
validation (scripts/experiment_inplay_dixon_coles.py, ADR-011).

Same shape as backfill_injuries.py: one real API call per fixture (no
bulk-by-season equivalent for /fixtures/events), sequential/resumable/
committed periodically, idempotent (ON CONFLICT DO NOTHING).

    python scripts/backfill_match_events.py --league MLS --seasons 2026
"""
import argparse
import logging
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ingestion.api_football import _api_football_fixture_id, _session, fetch_and_store_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


def backfill_events_for_league(conn, session, league_code: str,
                               season_labels: list[str] | None) -> tuple[int, int]:
    with conn.cursor() as cur:
        query = """SELECT m.match_id, m.external_ref FROM futbol.matches m
                   JOIN futbol.seasons s ON s.season_id = m.season_id
                   JOIN futbol.leagues l ON l.league_id = s.league_id
                   WHERE l.code = %s AND m.external_ref LIKE 'api-football:%%'
                     AND m.status = 'final'"""
        params: list = [league_code]
        if season_labels:
            query += " AND s.label = ANY(%s)"
            params.append(season_labels)
        cur.execute(query, params)
        matches = cur.fetchall()

    stored, skipped = 0, 0
    for i, (match_id, external_ref) in enumerate(matches, start=1):
        fixture_id = _api_football_fixture_id(external_ref)
        if fixture_id is None:
            skipped += 1
            continue
        try:
            with conn.cursor() as cur:
                n = fetch_and_store_events(session, cur, fixture_id)
            stored += n
        except Exception:
            conn.rollback()
            log.warning("fixture %d (match_id %d) failed -- skipping, continuing",
                       fixture_id, match_id, exc_info=True)
            skipped += 1
            continue
        if i % 20 == 0:
            conn.commit()
            log.info("progress: %d/%d fixtures processed (%d events so far)",
                     i, len(matches), stored)
    conn.commit()
    return stored, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", action="append", required=True,
                    choices=["EPL", "SERIE_A", "MLS", "LA_LIGA"])
    ap.add_argument("--seasons", nargs="+", default=None,
                    help="Season labels to backfill, e.g. 2026 (MLS) or 2024-25 (others). "
                         "Defaults to every season already linked to API-Football.")
    args = ap.parse_args()

    session = _session()
    conn = psycopg2.connect(DSN)
    total_stored = total_skipped = 0
    try:
        for league_code in args.league:
            stored, skipped = backfill_events_for_league(
                conn, session, league_code, args.seasons)
            total_stored += stored
            total_skipped += skipped
            log.info("%s: %d events stored, %d fixtures skipped",
                     league_code, stored, skipped)
    finally:
        conn.close()
    log.info("done: %d total events stored, %d fixtures skipped",
             total_stored, total_skipped)


if __name__ == "__main__":
    main()
