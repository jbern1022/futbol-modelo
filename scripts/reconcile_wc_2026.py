"""
Reconcile the 2026 World Cup rows with API-Football (Todoist 6hm4XP4q8xPMg9Jf).

Found 2026-10-29 (read-only): the DB had 100 of 104 fixtures. Six knockout rows were
still 'scheduled' though finished, and the two semi-finals, the third-place match and
the final were absent. Scores follow the 90-MINUTE convention (src/grading/grader.py:
1X2 grades on the 90-minute result), so this stores API `score.fulltime`, not `goals`
(which includes extra time). Match 100 (Norway v England, 1-1 after 90, 1-2 after extra
time) already follows the convention and carries the only graded WC predictions: it is
never touched except to set its went_to_ot flag.

What it plans (all printed first; nothing is written without --apply):
  updates       scheduled rows that finished -> final, 90-min score, ot/pens flags, pens
  inserts       fixtures the DB lacks (teams must already exist; none are created)
  fixture_ids   api_football_fixture_id for matched rows that lack it (NULL -> value)
  flag_fixes    went_to_ot / went_to_pens false -> true on finals the API says went to ET
  score_fixes   finals whose stored score differs from the 90-minute score. These
                OVERWRITE existing values and are applied only with --apply-score-fixes.

    python scripts/reconcile_wc_2026.py                       # dry run: calls the API once
    python scripts/reconcile_wc_2026.py --from-file wc.json   # dry run from a saved response
    python scripts/reconcile_wc_2026.py --apply --expect-updates 6 --expect-inserts 4
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import unicodedata

DONE = {"FT", "AET", "PEN"}
STAGE = {"3rd Place Final": "Third place", "Group Stage": "Group stage"}
_ALIASES = (("turkiye", "turkey"), ("congo dr", "dr congo"), ("cape verde islands", "cape verde"),
            ("&", "and"), ("usa", "united states"), ("korea republic", "south korea"))


def norm_team(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    for a, b in _ALIASES:
        n = n.replace(a, b)
    return n


def _stage(rnd: str) -> str:
    return "Group stage" if rnd.startswith("Group") else STAGE.get(rnd, rnd)


def _score_set(f: dict, flip: bool) -> dict:
    s = f["score"]
    hs, as_ = s["fulltime"]["home"], s["fulltime"]["away"]
    status = f["fixture"]["status"]["short"]
    ph, pa = s["penalty"]["home"], s["penalty"]["away"]
    if flip:
        hs, as_, ph, pa = as_, hs, pa, ph
    out = {"home_score": hs, "away_score": as_, "went_to_ot": status in {"AET", "PEN"},
           "went_to_pens": status == "PEN"}
    if status == "PEN":
        out.update(pens_home=ph, pens_away=pa)
    return out


def plan_reconciliation(api: list[dict], db: list[dict], team_ids: dict[str, int], season_id: int) -> dict:
    plan = {"updates": [], "inserts": [], "fixture_ids": [], "flag_fixes": [], "score_fixes": [],
            "unresolved": []}
    used: set[int] = set()
    for f in sorted(api, key=lambda x: x["fixture"]["date"]):
        status = f["fixture"]["status"]["short"]
        if status not in DONE:
            continue
        h, a = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
        nh, na = norm_team(h), norm_team(a)
        day = dt.date.fromisoformat(f["fixture"]["date"][:10])
        cands = [r for r in db if r["match_id"] not in used and {norm_team(r["home"]), norm_team(r["away"])} == {nh, na}
                 and abs((dt.date.fromisoformat(str(r["date"])[:10]) - day).days) <= 1]
        cands.sort(key=lambda r: abs((dt.date.fromisoformat(str(r["date"])[:10]) - day).days))
        if not cands:
            if nh not in team_ids or na not in team_ids:
                plan["unresolved"].append(f"fixture {f['fixture']['id']}: team not in DB: "
                                          f"{h if nh not in team_ids else a}")
                continue
            vals = _score_set(f, flip=False)
            plan["inserts"].append({
                "season_id": season_id, "home_team_id": team_ids[nh], "away_team_id": team_ids[na],
                "kickoff_utc": f["fixture"]["date"], "stage": _stage(f["league"]["round"]),
                "status": "final", "external_ref": f"api-football:{f['fixture']['id']}", **vals})
            continue
        r = cands[0]
        used.add(r["match_id"])
        flip = norm_team(r["home"]) != nh
        vals = _score_set(f, flip)
        if r["status"] != "final":
            plan["updates"].append({"match_id": r["match_id"], "set": {
                "status": "final", **vals, "api_football_fixture_id": f["fixture"]["id"]}})
            continue
        if r["api_id"] is None:
            plan["fixture_ids"].append({"match_id": r["match_id"],
                                        "set": {"api_football_fixture_id": f["fixture"]["id"]}})
        flags = {k: True for k in ("went_to_ot", "went_to_pens") if vals[k] and not r[k]}
        if flags:
            plan["flag_fixes"].append({"match_id": r["match_id"], "set": flags})
        if (r["home_score"], r["away_score"]) != (vals["home_score"], vals["away_score"]):
            plan["score_fixes"].append({"match_id": r["match_id"], "was": [r["home_score"], r["away_score"]],
                                        "set": {"home_score": vals["home_score"], "away_score": vals["away_score"]}})
    return plan


DB_SQL = """
SELECT m.match_id, m.kickoff_utc::date, m.status, coalesce(m.stage, ''), th.name, ta.name,
       m.home_team_id, m.away_team_id, m.home_score, m.away_score, m.went_to_ot, m.went_to_pens,
       m.api_football_fixture_id, m.season_id
FROM futbol.matches m
JOIN futbol.seasons s ON s.season_id = m.season_id JOIN futbol.leagues l ON l.league_id = s.league_id
JOIN futbol.teams th ON th.team_id = m.home_team_id JOIN futbol.teams ta ON ta.team_id = m.away_team_id
WHERE l.code = 'WC' AND s.label = '2026'
"""


def _load_db(cur):
    cur.execute(DB_SQL)
    rows, ids, season = [], {}, None
    for (mid, d, st, stage, hn, an, hid, aid, hs, as_, ot, pens, api_id, sid) in cur.fetchall():
        rows.append({"match_id": mid, "date": d, "status": st, "stage": stage, "home": hn, "away": an,
                     "home_id": hid, "away_id": aid, "home_score": hs, "away_score": as_,
                     "went_to_ot": ot, "went_to_pens": pens, "api_id": api_id})
        ids[norm_team(hn)], ids[norm_team(an)], season = hid, aid, sid
    return rows, ids, season


def _fetch_api() -> list[dict]:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from ingestion.api_football import _get, _session
    return _get(_session(), "fixtures", {"league": 1, "season": 2026})


def _set_sql(table_cols: dict) -> tuple[str, list]:
    return ", ".join(f"{k} = %s" for k in table_cols), list(table_cols.values())


def main() -> None:
    import psycopg2
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file", help="saved API-Football /fixtures response (skips the API call)")
    ap.add_argument("--apply", action="store_true", help="write updates, inserts, fixture ids and flag fixes")
    ap.add_argument("--apply-score-fixes", action="store_true",
                    help="also overwrite stored scores that differ from the 90-minute score")
    ap.add_argument("--expect-updates", type=int)
    ap.add_argument("--expect-inserts", type=int)
    args = ap.parse_args()

    api = json.load(open(args.from_file))["response"] if args.from_file else _fetch_api()
    conn = psycopg2.connect(os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol"))
    cur = conn.cursor()
    db, ids, season = _load_db(cur)
    plan = plan_reconciliation(api, db, ids, season)
    for k, v in plan.items():
        print(f"{k}: {len(v)}")
        for item in v:
            print("   ", item)
    bad = [k for k, e in (("updates", args.expect_updates), ("inserts", args.expect_inserts))
           if e is not None and len(plan[k]) != e]
    if bad:
        print(f"ABORT: planned counts differ from --expect for {bad}. Nothing written.")
        conn.close()
        sys.exit(2)
    if plan["unresolved"]:
        print("ABORT: unresolved teams (none are created automatically). Nothing written.")
        conn.close()
        sys.exit(2)
    if not args.apply:
        print("\ndry run -- nothing written (pass --apply)")
        conn.close()
        return
    for key in ("updates", "fixture_ids", "flag_fixes") + (("score_fixes",) if args.apply_score_fixes else ()):
        for item in plan[key]:
            sql, vals = _set_sql(item["set"])
            cur.execute(f"UPDATE futbol.matches SET {sql} WHERE match_id = %s", vals + [item["match_id"]])
    for ins in plan["inserts"]:
        cols = list(ins)
        cur.execute(f"INSERT INTO futbol.matches ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [ins[c] for c in cols])
    conn.commit()
    print("\napplied.")
    conn.close()


if __name__ == "__main__":
    main()
