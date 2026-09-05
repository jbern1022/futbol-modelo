"""
Entity resolution: map source-specific team/player names to canonical
futbol.teams / futbol.players rows.

Teams: small, stable set -> explicit seed mapping, fail loudly on unknowns.
Players: large, churning set -> upsert on source id (fbref_id/understat_id),
with a fuzzy-match assist for cross-source linking, and a manual review
queue for anything below the confidence threshold. Never silently guess.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

# ---------------------------------------------------------------
# Canonical team seed: canonical_name -> {source: source_name}
# Extend as leagues are added. Unknown source names raise.
# ---------------------------------------------------------------

TEAM_SEED: dict[str, dict[str, str]] = {
    # ---- Premier League ----
    "Arsenal":            {"fbref": "Arsenal", "understat": "Arsenal"},
    "Aston Villa":        {"fbref": "Aston Villa", "understat": "Aston Villa"},
    "Bournemouth":        {"fbref": "Bournemouth", "understat": "Bournemouth"},
    "Brentford":          {"fbref": "Brentford", "understat": "Brentford"},
    "Brighton":           {"fbref": "Brighton & Hove Albion", "understat": "Brighton"},
    "Chelsea":            {"fbref": "Chelsea", "understat": "Chelsea"},
    "Crystal Palace":     {"fbref": "Crystal Palace", "understat": "Crystal Palace"},
    "Everton":            {"fbref": "Everton", "understat": "Everton"},
    "Fulham":             {"fbref": "Fulham", "understat": "Fulham"},
    "Liverpool":          {"fbref": "Liverpool", "understat": "Liverpool"},
    "Manchester City":    {"fbref": "Manchester City", "understat": "Manchester City"},
    "Manchester United":  {"fbref": "Manchester United", "understat": "Manchester United"},
    "Newcastle":          {"fbref": "Newcastle United", "understat": "Newcastle United"},
    "Nottingham Forest":  {"fbref": "Nottingham Forest", "understat": "Nottingham Forest"},
    "Tottenham":          {"fbref": "Tottenham Hotspur", "understat": "Tottenham"},
    "West Ham":           {"fbref": "West Ham United", "understat": "West Ham"},
    "Wolves":             {"fbref": "Wolverhampton Wanderers", "understat": "Wolverhampton Wanderers"},
    "Leeds United":       {"fbref": "Leeds United", "understat": "Leeds"},
    "Burnley":            {"fbref": "Burnley", "understat": "Burnley"},
    "Sunderland":         {"fbref": "Sunderland", "understat": "Sunderland"},
    "Leicester City":     {"fbref": "Leicester City", "understat": "Leicester"},
    "Norwich City":       {"fbref": "Norwich City", "understat": "Norwich"},
    "Watford":            {"fbref": "Watford", "understat": "Watford"},
    "Luton Town":         {"fbref": "Luton Town", "understat": "Luton"},
    "Sheffield United":   {"fbref": "Sheffield United", "understat": "Sheffield United"},
    "Ipswich Town":       {"fbref": "Ipswich Town", "understat": "Ipswich"},
    "Southampton":        {"fbref": "Southampton", "understat": "Southampton"},
    "Hull City":          {"fbref": "Hull City", "understat": "Hull"},
    "Coventry City":      {"fbref": "Coventry City", "understat": "Coventry City"},
    "Real Madrid":        {"fbref": "Real Madrid", "understat": "Real Madrid"},
    "Barcelona":          {"fbref": "Barcelona", "understat": "Barcelona"},
    "Atletico Madrid":    {"fbref": "Atlético Madrid", "understat": "Atletico Madrid"},
    "Athletic Club":      {"fbref": "Athletic Club", "understat": "Athletic Club"},
    "Real Sociedad":      {"fbref": "Real Sociedad", "understat": "Real Sociedad"},
    "Real Betis":         {"fbref": "Real Betis", "understat": "Real Betis"},
    "Villarreal":         {"fbref": "Villarreal", "understat": "Villarreal"},
    "Valencia":           {"fbref": "Valencia", "understat": "Valencia"},
    "Sevilla":            {"fbref": "Sevilla", "understat": "Sevilla"},
    "Celta Vigo":         {"fbref": "Celta Vigo", "understat": "Celta Vigo"},
    "Osasuna":            {"fbref": "Osasuna", "understat": "Osasuna"},
    "Getafe":             {"fbref": "Getafe", "understat": "Getafe"},
    "Mallorca":           {"fbref": "Mallorca", "understat": "Mallorca"},
    "Girona":             {"fbref": "Girona", "understat": "Girona"},
    "Rayo Vallecano":     {"fbref": "Rayo Vallecano", "understat": "Rayo Vallecano"},
    "Alaves":             {"fbref": "Alavés", "understat": "Alaves"},
    "Espanyol":           {"fbref": "Espanyol", "understat": "Espanyol"},
    "Las Palmas":         {"fbref": "Las Palmas", "understat": "Las Palmas"},
    "Leganes":            {"fbref": "Leganés", "understat": "Leganes"},
    "Valladolid":         {"fbref": "Valladolid", "understat": "Real Valladolid"},
    "Levante":            {"fbref": "Levante", "understat": "Levante"},
    "Elche":              {"fbref": "Elche", "understat": "Elche"},
    "Real Oviedo":        {"fbref": "Oviedo", "understat": "Real Oviedo"},
    # promoted sides vary by season — add per-season during backfill
    # ---- Serie A ----
    "Atalanta":           {"fbref": "Atalanta", "understat": "Atalanta"},
    "Bologna":            {"fbref": "Bologna", "understat": "Bologna"},
    "Cagliari":           {"fbref": "Cagliari", "understat": "Cagliari"},
    "Como":               {"fbref": "Como", "understat": "Como"},
    "Fiorentina":         {"fbref": "Fiorentina", "understat": "Fiorentina"},
    "Genoa":              {"fbref": "Genoa", "understat": "Genoa"},
    "Inter":              {"fbref": "Internazionale", "understat": "Inter"},
    "Juventus":           {"fbref": "Juventus", "understat": "Juventus"},
    "Lazio":              {"fbref": "Lazio", "understat": "Lazio"},
    "Milan":              {"fbref": "Milan", "understat": "AC Milan"},
    "Napoli":             {"fbref": "Napoli", "understat": "Napoli"},
    "Roma":               {"fbref": "Roma", "understat": "Roma"},
    "Torino":             {"fbref": "Torino", "understat": "Torino"},
    "Udinese":            {"fbref": "Udinese", "understat": "Udinese"},
    "Verona":             {"fbref": "Hellas Verona", "understat": "Verona"},
    "Cremonese":          {"fbref": "Cremonese", "understat": "Cremonese"},
    "Lecce":              {"fbref": "Lecce", "understat": "Lecce"},
    "Parma":              {"fbref": "Parma", "understat": "Parma Calcio 1913"},
    "Pisa":               {"fbref": "Pisa", "understat": "Pisa"},
    "Sassuolo":           {"fbref": "Sassuolo", "understat": "Sassuolo"},
    "Empoli":             {"fbref": "Empoli", "understat": "Empoli"},
    "Monza":              {"fbref": "Monza", "understat": "Monza"},
    "Spezia":             {"fbref": "Spezia", "understat": "Spezia"},
    "Sampdoria":          {"fbref": "Sampdoria", "understat": "Sampdoria"},
    "Salernitana":        {"fbref": "Salernitana", "understat": "Salernitana"},
    "Venezia":            {"fbref": "Venezia", "understat": "Venezia"},
    "Frosinone":          {"fbref": "Frosinone", "understat": "Frosinone"},

    # ---- World Cup 2026: full 48-team field ----
    # Hosts
    "Canada":             {"fbref": "Canada"},
    "Mexico":             {"fbref": "Mexico"},
    "United States":      {"fbref": "United States"},
    # CONMEBOL
    "Argentina":          {"fbref": "Argentina"},
    "Brazil":             {"fbref": "Brazil"},
    "Colombia":           {"fbref": "Colombia"},
    "Ecuador":            {"fbref": "Ecuador"},
    "Paraguay":           {"fbref": "Paraguay"},
    "Uruguay":            {"fbref": "Uruguay"},
    # UEFA
    "Austria":            {"fbref": "Austria"},
    "Belgium":            {"fbref": "Belgium"},
    "Bosnia and Herzegovina": {"fbref": "Bosnia–Herz"},
    "Croatia":            {"fbref": "Croatia"},
    "Czechia":            {"fbref": "Czechia"},
    "England":            {"fbref": "England"},
    "France":             {"fbref": "France"},
    "Germany":            {"fbref": "Germany"},
    "Netherlands":        {"fbref": "Netherlands"},
    "Norway":             {"fbref": "Norway"},
    "Portugal":           {"fbref": "Portugal"},
    "Scotland":           {"fbref": "Scotland"},
    "Spain":              {"fbref": "Spain"},
    "Sweden":             {"fbref": "Sweden"},
    "Switzerland":        {"fbref": "Switzerland"},
    "Turkey":             {"fbref": "Türkiye"},
    # AFC
    "Australia":          {"fbref": "Australia"},
    "Iraq":               {"fbref": "Iraq"},
    "Iran":               {"fbref": "IR Iran"},
    "Japan":              {"fbref": "Japan"},
    "Jordan":             {"fbref": "Jordan"},
    "South Korea":        {"fbref": "Korea Republic"},
    "Qatar":              {"fbref": "Qatar"},
    "Saudi Arabia":       {"fbref": "Saudi Arabia"},
    "Uzbekistan":         {"fbref": "Uzbekistan"},
    # CAF
    "Algeria":            {"fbref": "Algeria"},
    "Cape Verde":         {"fbref": "Cabo Verde"},
    "DR Congo":           {"fbref": "Congo DR"},
    "Ivory Coast":        {"fbref": "Côte d'Ivoire"},
    "Egypt":              {"fbref": "Egypt"},
    "Ghana":              {"fbref": "Ghana"},
    "Morocco":            {"fbref": "Morocco"},
    "Senegal":            {"fbref": "Senegal"},
    "South Africa":       {"fbref": "South Africa"},
    "Tunisia":            {"fbref": "Tunisia"},
    # CONCACAF
    "Curacao":            {"fbref": "Curaçao"},
    "Haiti":              {"fbref": "Haiti"},
    "Panama":             {"fbref": "Panama"},
    # OFC
    "New Zealand":        {"fbref": "New Zealand"},
}


class UnknownTeamError(Exception):
    pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().strip()


# reverse index: (source, normalized source name) -> canonical
_REVERSE = {
    (src, _norm(name)): canon
    for canon, sources in TEAM_SEED.items()
    for src, name in sources.items()
}


def resolve_team(source: str, name: str) -> str:
    """Source team name -> canonical name. Raises on unknown (by design)."""
    key = (source, _norm(name))
    if key in _REVERSE:
        return _REVERSE[key]
    raise UnknownTeamError(
        f"Unmapped team {name!r} from {source!r}. "
        f"Add it to TEAM_SEED — do not guess."
    )


# ---------------------------------------------------------------
# Player linking: primary key is the source id; fuzzy name match
# only assists cross-source linking, gated by threshold.
# ---------------------------------------------------------------

FUZZY_ACCEPT = 0.92   # auto-link
FUZZY_REVIEW = 0.80   # queue for manual review below accept, above this


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def link_player(cur, source: str, source_id: str, full_name: str,
                team_canonical: str, position: str | None = None) -> int:
    """
    Upsert a player and return player_id.
    1. Exact hit on source id -> done.
    2. Else fuzzy match against existing players on the same team.
       >= FUZZY_ACCEPT: attach this source id to that row.
       in review band:  insert into ingest_review queue, create new row.
       below:           new player row.
    """
    id_col = f"{source}_id"
    cur.execute(f"SELECT player_id FROM futbol.players WHERE {id_col} = %s", (source_id,))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        """SELECT p.player_id, p.full_name FROM futbol.players p
           JOIN futbol.player_match_stats s USING (player_id)
           JOIN futbol.teams t ON t.team_id = s.team_id
           WHERE t.name = %s GROUP BY p.player_id, p.full_name""",
        (team_canonical,))
    best_id, best_score, best_name = None, 0.0, None
    for pid, existing in cur.fetchall():
        sc = name_similarity(full_name, existing)
        if sc > best_score:
            best_id, best_score, best_name = pid, sc, existing

    if best_id and best_score >= FUZZY_ACCEPT:
        cur.execute(
            f"UPDATE futbol.players SET {id_col} = %s WHERE player_id = %s",
            (source_id, best_id))
        return best_id

    cur.execute(
        f"""INSERT INTO futbol.players (full_name, position, {id_col})
            VALUES (%s, %s, %s) RETURNING player_id""",
        (full_name, position, source_id))
    new_id = cur.fetchone()[0]

    if best_id and best_score >= FUZZY_REVIEW:
        cur.execute(
            """INSERT INTO futbol.ingest_review
               (kind, detail) VALUES ('player_possible_duplicate', %s)""",
            (f"{full_name} ({source}:{source_id}) ~ {best_name} "
             f"(player_id={best_id}) score={best_score:.2f}",))
    return new_id
