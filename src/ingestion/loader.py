"""
Ingestion loader: soccerdata (FBref + Understat) -> futbol schema.

Two entry points:
    python -m ingestion.loader backfill --league EPL --seasons 2122 2223 2324 2425 2526
    python -m ingestion.loader matchday --league SERIE_A

Design rules:
  - soccerdata handles scraping etiquette + caching (FBref requires
    ~3s between requests and bans rude clients; the on-disk cache in
    ~/.soccerdata means a re-run costs zero requests).
  - Every write is an idempotent upsert keyed on external ids, so
    re-running a backfill is always safe.
  - Unknown team names raise (entities.resolve_team). Fix the seed,
    re-run. Silent guessing is how datasets rot.

soccerdata league keys:  'ENG-Premier League', 'ITA-Serie A'
Season key format:       '2425' = 2024-25
"""
from __future__ import annotations

import argparse
import logging
import os

import psycopg2

from . import entities

log = logging.getLogger("ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

LEAGUES = {
    "EPL":     {"soccerdata": "ENG-Premier League", "code": "EPL",     "name": "Premier League"},
    "SERIE_A": {"soccerdata": "ITA-Serie A",        "code": "SERIE_A", "name": "Serie A"},
    "LA_LIGA": {"soccerdata": "ESP-La Liga",        "code": "LA_LIGA", "name": "La Liga"},
    "WC":      {"soccerdata": "INT-World Cup",      "code": "WC",      "name": "World Cup",
                "is_international": True},
}

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")


# ------------------------------------------------------------------
# Upsert helpers (idempotent by design)
# ------------------------------------------------------------------

def upsert_league(cur, code: str, name: str, is_international: bool = False) -> int:
    cur.execute(
        """INSERT INTO futbol.leagues (code, name, is_international) VALUES (%s, %s, %s)
           ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
           RETURNING league_id""", (code, name, is_international))
    return cur.fetchone()[0]


def upsert_season(cur, league_id: int, label: str) -> int:
    cur.execute(
        """INSERT INTO futbol.seasons (league_id, label) VALUES (%s, %s)
           ON CONFLICT (league_id, label) DO UPDATE SET label = EXCLUDED.label
           RETURNING season_id""", (league_id, label))
    return cur.fetchone()[0]


def upsert_team(cur, canonical: str) -> int:
    cur.execute(
        """INSERT INTO futbol.teams (name) VALUES (%s)
           ON CONFLICT (name) DO NOTHING""", (canonical,))
    cur.execute("SELECT team_id FROM futbol.teams WHERE name = %s", (canonical,))
    return cur.fetchone()[0]


def upsert_match(cur, season_id, home_id, away_id, kickoff, hg, ag, status, ext_ref) -> int:
    cur.execute(
        """INSERT INTO futbol.matches
             (season_id, home_team_id, away_team_id, kickoff_utc,
              home_goals, away_goals, status, external_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (season_id, home_team_id, away_team_id, kickoff_utc)
           DO UPDATE SET home_goals = EXCLUDED.home_goals,
                         away_goals = EXCLUDED.away_goals,
                         status     = EXCLUDED.status
           RETURNING match_id""",
        (season_id, home_id, away_id, kickoff, hg, ag, status, ext_ref))
    return cur.fetchone()[0]


# ------------------------------------------------------------------
# Understat: schedule + team xG + event-level shots
# ------------------------------------------------------------------

def load_understat(conn, league_key: str, seasons: list[str]):
    import soccerdata as sd
    us = sd.Understat(leagues=[league_key], seasons=seasons)
    lg = next(v for v in LEAGUES.values() if v["soccerdata"] == league_key)

    with conn.cursor() as cur:
        league_id = upsert_league(cur, lg["code"], lg["name"])

        sched = us.read_schedule().reset_index()
        log.info("Understat schedule: %d rows", len(sched))
        for _, r in sched.iterrows():
            season_id = upsert_season(cur, league_id, _season_label(r["season"]))
            home = entities.resolve_team("understat", r["home_team"])
            away = entities.resolve_team("understat", r["away_team"])
            hid, aid = upsert_team(cur, home), upsert_team(cur, away)
            status = "final" if r.notna().get("home_goals", False) else "scheduled"
            mid = upsert_match(cur, season_id, hid, aid, r["date"],
                               _int(r.get("home_goals")), _int(r.get("away_goals")),
                               status, f"understat:{r.get('game_id', '')}")
            # team xG into team_match_stats
            for tid, xg, is_home in ((hid, r.get("home_xg"), True),
                                     (aid, r.get("away_xg"), False)):
                cur.execute(
                    """INSERT INTO futbol.team_match_stats (match_id, team_id, is_home, xg)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (match_id, team_id)
                       DO UPDATE SET xg = EXCLUDED.xg""",
                    (mid, tid, is_home, _num(xg)))
        conn.commit()

        # event-level shots (feeds the custom xG model in v3)
        shots = us.read_shot_events().reset_index()
        log.info("Understat shots: %d rows", len(shots))
        for _, s in shots.iterrows():
            cur.execute(
                "SELECT match_id FROM futbol.matches WHERE external_ref = %s",
                (f"understat:{s['game_id']}",))
            row = cur.fetchone()
            if not row:
                continue
            team = entities.resolve_team("understat", s["team"])
            tid = upsert_team(cur, team)
            pid = entities.link_player(cur, "understat", str(s["player_id"]),
                                       s["player"], team)
            cur.execute(
                """INSERT INTO futbol.shots
                     (match_id, player_id, team_id, minute, x, y,
                      situation, body_part, result, source_xg)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (match_id, player_id, minute, x, y, situation, result)
                   DO NOTHING""",
                (row[0], pid, tid, _int(s.get("minute")), _num(s.get("location_x")),
                 _num(s.get("location_y")), _clean(s.get("situation")),
                 _clean(s.get("body_part")), _clean(s.get("result")),
                 _num(s.get("xg"))))
        conn.commit()


# ------------------------------------------------------------------
# FBref: the count stats Understat lacks — corners, saves, SOT, cards
# ------------------------------------------------------------------

def load_fbref(conn, league_key: str, seasons: list[str]):
    import soccerdata as sd
    import pandas as pd
    fb = sd.FBref(leagues=[league_key], seasons=seasons)

    with conn.cursor() as cur:
        # team match-level stats
        for stat_type, cols in (
            ("schedule", None),  # ensures fixture alignment
            ("misc", {"CrdY": "yellows", "CrdR": "reds", "Fls": "fouls"}),
            ("shooting", {"Sh": "shots", "SoT": "shots_on_target"}),
            ("passing_types", {"CK": "corners"}),
            ("keeper", {"Saves": "saves"}),
        ):
            if stat_type == "schedule":
                continue
            try:
                df = fb.read_team_match_stats(stat_type=stat_type).reset_index()
            except ValueError as e:
                if "Invalid argument: stat_type" in str(e):
                    log.warning("FBref %s not available for %s — skipping (%s)",
                               stat_type, league_key, e)
                    continue
                raise
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[-1] if c[-1] else c[0] for c in df.columns]
            log.info("FBref %s: %d rows", stat_type, len(df))
            for _, r in df.iterrows():
                team = entities.resolve_team("fbref", r["team"])
                tid = upsert_team(cur, team)
                mid = _find_match(cur, r, tid)
                if mid is None:
                    continue
                sets = ", ".join(f"{v} = %s" for v in cols.values())
                vals = [_num(r.get(k)) for k in cols]
                cur.execute(
                    f"""UPDATE futbol.team_match_stats SET {sets}
                        WHERE match_id = %s AND team_id = %s""",
                    (*vals, mid, tid))
            conn.commit()

        # player match-level stats (summary covers shots/goals/minutes)
        df = fb.read_player_match_stats(stat_type="summary").reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[-1] if c[-1] else c[0] for c in df.columns]
        log.info("FBref player summary: %d rows", len(df))
        for _, r in df.iterrows():
            team = entities.resolve_team("fbref", r["team"])
            tid = upsert_team(cur, team)
            mid = _find_match(cur, r, tid)
            if mid is None:
                continue
            pid = entities.link_player(cur, "fbref", str(r.get("player_id", r["player"])),
                                       r["player"], team, _clean(r.get("position")))
            cur.execute(
                """INSERT INTO futbol.player_match_stats
                     (match_id, player_id, team_id, minutes, goals, assists,
                      shots, shots_on_target, xg, xa)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (match_id, player_id) DO UPDATE SET
                      minutes = EXCLUDED.minutes, goals = EXCLUDED.goals,
                      shots = EXCLUDED.shots,
                      shots_on_target = EXCLUDED.shots_on_target""",
                (mid, pid, tid, _int(r.get("Min")), _int(r.get("Gls")),
                 _int(r.get("Ast")), _int(r.get("Sh")), _int(r.get("SoT")),
                 _num(r.get("xG")), _num(r.get("xAG"))))
        conn.commit()


def load_world_cup(conn, seasons: list[str]):
    """
    World Cup via FBref schedule only (Understat doesn't cover internationals).
    Handles: score parsing incl. AET/penalties notation, knockout stage flag,
    and the smaller/looser team seed (national teams, no club aliases).
    """
    import soccerdata as sd
    fb = sd.FBref(leagues=["INT-World Cup"], seasons=seasons)
    lg = LEAGUES["WC"]

    with conn.cursor() as cur:
        league_id = upsert_league(cur, lg["code"], lg["name"],
                                  is_international=True)
        sched = fb.read_schedule().reset_index()
        log.info("World Cup schedule: %d rows", len(sched))

        for _, r in sched.iterrows():
            season_id = upsert_season(cur, league_id, str(r["season"]))
            home = entities.resolve_team("fbref", r["home_team"])
            away = entities.resolve_team("fbref", r["away_team"])
            hid, aid = upsert_team(cur, home), upsert_team(cur, away)

            hg, ag, went_et, went_pens = _parse_score(r.get("score"))
            status = "final" if hg is not None else "scheduled"
            stage = r.get("round")  # e.g. 'Round of 16', 'Quarter-finals'

            cur.execute(
                """INSERT INTO futbol.matches
                     (season_id, home_team_id, away_team_id, kickoff_utc,
                      stage, home_goals, away_goals, went_to_et, went_to_pens,
                      status, external_ref)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (season_id, home_team_id, away_team_id, kickoff_utc)
                   DO UPDATE SET
                     home_goals = COALESCE(EXCLUDED.home_goals, futbol.matches.home_goals),
                     away_goals = COALESCE(EXCLUDED.away_goals, futbol.matches.away_goals),
                     status = CASE WHEN EXCLUDED.status = 'final'
                                    OR futbol.matches.status <> 'final'
                                   THEN EXCLUDED.status ELSE futbol.matches.status END,
                     went_to_et = COALESCE(EXCLUDED.went_to_et, futbol.matches.went_to_et),
                     went_to_pens = COALESCE(EXCLUDED.went_to_pens, futbol.matches.went_to_pens)
                   RETURNING match_id""",
                (season_id, hid, aid, r["date"], stage, hg, ag,
                 went_et, went_pens, status, f"fbref-wc:{r.get('game_id','')}"))
        conn.commit()
    log.info("World Cup load complete")


def _parse_score(raw) -> tuple[int | None, int | None, bool, bool]:
    """
    FBref score formats seen: '2-1', '1-1 (4-3)' [penalties],
    '2-1 (AET)'. Returns (home_goals, away_goals, went_to_et, went_to_pens).
    90'-result goals are used for grading (standard convention);
    the paren group, if present, signals ET/pens occurred.
    """
    import pandas as pd, re
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, None, False, False
    s = str(raw).strip()
    m = re.match(r"(\d+)[\u2013\-](\d+)", s)
    if not m:
        return None, None, False, False
    hg, ag = int(m.group(1)), int(m.group(2))
    went_pens = "(" in s and any(c.isdigit() for c in s.split("(")[-1])
    went_et = "aet" in s.lower() or went_pens
    return hg, ag, went_et, went_pens


def _find_match(cur, row, team_id) -> int | None:
    """Locate the match by date + team participation (source-agnostic join)."""
    cur.execute(
        """SELECT match_id FROM futbol.matches
           WHERE DATE(kickoff_utc) = DATE(%s)
             AND (home_team_id = %s OR away_team_id = %s)""",
        (row["date"], team_id, team_id))
    r = cur.fetchone()
    return r[0] if r else None


# ------------------------------------------------------------------

def _clean(v):
    """Convert any pandas missing-value sentinel (NaN, NaT, pd.NA) to None."""
    import pandas as pd
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _season_label(s) -> str:
    s = str(s)
    return f"20{s[:2]}-{s[2:]}" if len(s) == 4 else s

def _int(v):
    try:
        import pandas as pd
        return None if v is None or pd.isna(v) else int(v)
    except (TypeError, ValueError):
        return None

def _num(v):
    try:
        import pandas as pd
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill", "matchday"])
    ap.add_argument("--league", required=True, choices=list(LEAGUES))
    ap.add_argument("--seasons", nargs="+", default=["2526"])
    ap.add_argument("--skip-understat", action="store_true",
                    help="Skip Understat stage (use when re-running after "
                         "Understat already committed but FBref failed)")
    ap.add_argument("--skip-fbref", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DSN)
    try:
        if args.league == "WC":
            load_world_cup(conn, args.seasons)
        else:
            lg = LEAGUES[args.league]["soccerdata"]
            if not args.skip_understat:
                load_understat(conn, lg, args.seasons)
            else:
                log.info("skipping Understat stage")
            if not args.skip_fbref:
                _load_fbref_with_retry(conn, lg, args.seasons)
            else:
                log.info("skipping FBref stage")
    finally:
        conn.close()
    log.info("done: %s %s %s", args.mode, args.league, args.seasons)


def _load_fbref_with_retry(conn, lg, seasons, attempts=3):
    import time
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            load_fbref(conn, lg, seasons)
            return
        except ValueError as e:
            if "No objects to concatenate" not in str(e):
                raise
            last_err = e
            wait = 10 * attempt
            log.info("FBref season-index came back empty (attempt %d/%d), "
                     "retrying in %ds...", attempt, attempts, wait)
            time.sleep(wait)
    raise RuntimeError(
        f"FBref season-index kept returning empty after {attempts} attempts. "
        f"This is usually transient bot-detection — try again in a few minutes, "
        f"or run with --skip-understat to retry just this stage."
    ) from last_err


if __name__ == "__main__":
    main()
