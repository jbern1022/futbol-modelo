"""
One-off audit (Todoist: "futbol-modelo: audit player full_name quality
after injuries backfill"). Checks whether the pre-fix
fetch_and_store_injuries() bug (silently overwriting a player's
full_name with API-Football's abbreviated /injuries names) actually
degraded other players beyond the one confirmed case (player_id 2476,
"Andrew Thomas" -> "A. Thomas", manually fixed 2026-09-29).

For a sample of players with an abbreviated-looking current name
("X. Surname") who appear in player_injuries (i.e. were touched by the
backfill), re-fetches /fixtures/players for one of their known matches
-- the endpoint load_fixture_players() already trusts as the primary
name source -- and compares. A mismatch where /fixtures/players gives
a fuller name is a real degradation candidate; auto-fixes those
(same direction as the one already-confirmed fix), does NOT touch
players where both sources agree (already-abbreviated is the norm for
API-Football generally, not unique to this bug -- see
resolve_player_for_odds()'s comment on "C. Tzolis"-style names).

    python scripts/audit_player_names.py --limit 100
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg2

from ingestion.api_football import _api_football_fixture_id, _get, _session

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")

CANDIDATES_SQL = """
SELECT DISTINCT ON (pl.player_id)
    pl.player_id, pl.full_name, pl.api_football_id, m.external_ref
FROM futbol.players pl
JOIN futbol.player_injuries pi ON pi.player_id = pl.player_id
JOIN futbol.player_match_stats pms ON pms.player_id = pl.player_id AND pms.minutes >= 45
JOIN futbol.matches m ON m.match_id = pms.match_id AND m.external_ref LIKE 'api-football:%%'
WHERE pl.full_name ~ '^[A-Z]\\. '
ORDER BY pl.player_id, m.kickoff_utc DESC
LIMIT %s;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write fixes (default is dry-run/report only)")
    args = ap.parse_args()

    session = _session()
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(CANDIDATES_SQL, (args.limit,))
        candidates = cur.fetchall()
    print(f"Checking {len(candidates)} abbreviated-name players against /fixtures/players...\n")

    fixed, confirmed_ok, no_data = 0, 0, 0
    with conn.cursor() as cur:
        for player_id, current_name, api_player_id, external_ref in candidates:
            fixture_id = _api_football_fixture_id(external_ref)
            if fixture_id is None:
                continue
            try:
                resp = _get(session, "fixtures/players", {"fixture": fixture_id})
            except Exception as e:
                print(f"  [skip] {current_name} (player_id={player_id}): API error {e}")
                continue

            real_name = None
            for team_block in resp:
                for p in team_block.get("players", []):
                    if p["player"]["id"] == api_player_id:
                        real_name = p["player"]["name"]
                        break

            if real_name is None:
                no_data += 1
                continue
            if real_name == current_name:
                confirmed_ok += 1
                continue
            if len(real_name) > len(current_name) and " " in real_name:
                print(f"  [DEGRADED] player_id={player_id}: {current_name!r} -> should be {real_name!r}")
                if args.apply:
                    cur.execute("UPDATE futbol.players SET full_name = %s WHERE player_id = %s",
                              (real_name, player_id))
                fixed += 1
            else:
                print(f"  [different, not clearly better] player_id={player_id}: "
                     f"{current_name!r} vs {real_name!r} -- not touching")
    if args.apply:
        conn.commit()
    conn.close()

    print(f"\ndone: {len(candidates)} checked, {fixed} degraded "
          f"({'fixed' if args.apply else 'NOT fixed -- rerun with --apply'}), "
          f"{confirmed_ok} confirmed already-correct, {no_data} had no comparable data")


if __name__ == "__main__":
    main()
