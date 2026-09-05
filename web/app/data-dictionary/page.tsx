import Link from "next/link";

interface Column {
  name: string;
  type: string;
  note?: string;
}

interface Table {
  name: string;
  description: string;
  columns: Column[];
}

const TABLES: Table[] = [
  {
    name: "leagues",
    description: "One row per competition. sport distinguishes soccer from the planned NFL/NBA expansion.",
    columns: [
      { name: "code", type: "text", note: "'EPL', 'SERIE_A', 'MLS', 'LA_LIGA', 'WC'" },
      { name: "is_international", type: "boolean", note: "true only for World Cup" },
      { name: "sport", type: "text", note: "'soccer' | 'basketball' | 'football' — every league is 'soccer' today; the other two exist for the planned NFL/NBA build" },
    ],
  },
  {
    name: "seasons",
    description: "Per-league season. Label format is NOT uniform across leagues — a real bug (fixed) once made these disagree between ingestion paths for the same real season.",
    columns: [
      { name: "label", type: "text", note: "Hyphenated 'YYYY-YY' for cross-year leagues (EPL, SERIE_A, LA_LIGA — e.g. '2026-27'); bare 'YYYY' for single-calendar-year competitions (MLS, WC — e.g. '2026'). Both ingestion paths (loader.py, api_football.py) must agree on this per league or a season silently duplicates." },
    ],
  },
  {
    name: "teams / players",
    description: "Shared entity tables across every league and (eventually) every sport. External ids exist purely for de-duplicating the same real-world team/player across three independent data sources.",
    columns: [
      { name: "fbref_id / understat_id / api_football_id", type: "text/text/int", note: "Nullable — a team only has an id for the sources that actually cover it. Name-based aliasing (src/ingestion/entities.py) resolves the same team across sources when ids don't overlap." },
      { name: "players.position", type: "text", note: "'GK'/'DF'/'MF'/'FW' — free text from the source, not an enum" },
    ],
  },
  {
    name: "matches",
    description: "One row per fixture, shared across all leagues/sports. home_score/away_score were renamed from home_goals/away_goals (generalizing off soccer terminology) — check you're on a build past that rename.",
    columns: [
      { name: "status", type: "text", note: "'scheduled' | 'live' | 'final' | 'postponed'" },
      { name: "home_score / away_score", type: "int", note: "NULL until final" },
      { name: "went_to_ot", type: "boolean", note: "Renamed from went_to_et — extra time/overtime, applies to any sport" },
      { name: "went_to_pens", type: "boolean", note: "Soccer/knockout-tournament specific (penalty shootout) — deliberately NOT generalized, NFL/NBA have no equivalent and this column will simply stay false for them" },
      { name: "external_ref", type: "text", note: "e.g. 'api-football:12345', 'understat:67890' — the source event id, prefixed by source" },
    ],
  },
  {
    name: "team_match_stats / player_match_stats",
    description: "Soccer-specific box-score stats, one row per team/player per match. Deliberately NOT shared with other sports (see team_match_stats_nfl below) — per-sport tables chosen over a shared core + JSONB column for full type safety and easy indexing.",
    columns: [
      { name: "xg / xa", type: "numeric", note: "Understat only — API-Football's tier doesn't include xG, so these are NULL for matches sourced only from API-Football (e.g. current-season EPL/SERIE_A fixtures pulled via the --primary stopgap path before FBref/Understat catch up)" },
      { name: "ppda", type: "numeric", note: "Pressing intensity — Understat only" },
      { name: "corners, shots, shots_on_target, possession_pct, fouls, yellows, reds, saves, deep_completions", type: "various", note: "FBref/API-Football; coverage varies by league — see the World Cup exception below" },
    ],
  },
  {
    name: "team_match_stats_nfl / player_match_stats_nfl",
    description: "Empty as of this writing — schema prep only, ahead of the actual NFL ingestion adapter. Column list is a best-effort standard box-score set matching nflverse/nfl_data_py's shape; expect adjustment once real data starts flowing.",
    columns: [
      { name: "team_match_stats_nfl", type: "table", note: "total/passing/rushing yards, turnovers, sacks, penalties, first downs, third-down conversions, time of possession" },
      { name: "player_match_stats_nfl", type: "table", note: "position, passing/rushing/receiving stat lines, defensive tackles/sacks (sacks is NUMERIC(3,1) — half-sacks are real)" },
    ],
  },
  {
    name: "shots",
    description: "Event-level shot data (Understat only) — coordinates, situation, body part, Understat's own xG as a benchmark. Feeds a planned custom xG model (v3); also the reason MLS/API-Football-only leagues have no shot-level detail.",
    columns: [
      { name: "x, y", type: "numeric", note: "Understat's normalized pitch coordinates" },
      { name: "source_xg", type: "numeric", note: "Understat's xG for this shot — the benchmark a future in-house model would be compared against" },
    ],
  },
  {
    name: "model_versions",
    description: "One row per distinct (model, config), not per prediction run. This was broken for a while — version_tag used to be unique per fixture, which meant every slate-generation call minted a new throwaway row and the registry never actually deduplicated anything. Fixed: version_tag is now stable per league+code-version.",
    columns: [
      { name: "params", type: "jsonb", note: "Real hyperparameters + feature lists as of the fix, not free-text notes" },
      { name: "train_metrics", type: "jsonb", note: "Real out-of-fold error metrics (e.g. MAE) where computed inline; not always populated for every model" },
    ],
  },
  {
    name: "predictions",
    description: "The immutable ledger. INSERT-only (a trigger rejects UPDATE/DELETE outright); another trigger rejects any row locked at or after its match's kickoff.",
    columns: [
      { name: "market", type: "text", note: "CHECK-constrained: '1X2','BTTS','TOTAL_GOALS','CORNERS','SOT','PLAYER_GOALS','PLAYER_SAVES' (soccer, live) plus 'MONEYLINE','SPREAD','TOTAL_POINTS' (NFL/NBA, schema prep only — nothing writes these yet)" },
      { name: "side", type: "text", note: "Semantics depend on market: 'home'/'draw'/'away' for 1X2, 'yes'/'no' for BTTS, 'over'/'under' for line markets, 'home'/'away' for SPREAD/MONEYLINE (which team the prediction concerns)" },
      { name: "line", type: "numeric", note: "NULL where not applicable (1X2, BTTS, MONEYLINE); the threshold for O/U markets; the signed spread for SPREAD" },
      { name: "probability", type: "numeric", note: "CHECK-constrained to the open interval (0,1) — never exactly 0 or 1" },
    ],
  },
  {
    name: "prediction_grades",
    description: "Separate, append-only. The prediction row itself is never touched when grading happens.",
    columns: [
      { name: "outcome", type: "text", note: "'hit' | 'miss' | 'void' — void covers pushes (line lands exactly on the actual value) and postponed/abandoned matches" },
      { name: "actual_value", type: "numeric", note: "The observed number graded against — a signed margin for SPREAD, a count for line markets, goal difference for 1X2" },
    ],
  },
  {
    name: "ingest_review",
    description: "Queue for entity-resolution ambiguities a human should check (e.g. a possible-duplicate player). Empty as of this writing — surfaced by scripts/review_queue.py, not shown anywhere in the UI.",
    columns: [],
  },
  {
    name: "pipeline_runs",
    description: "Backing store for a future data-freshness indicator. The table exists but nothing writes to it yet — auto_slate.py/auto_grade.py/the ingestion scripts still need a small wrapper to record start/finish/status. Known gap, tracked in Todoist.",
    columns: [],
  },
];

export default function DataDictionaryPage() {
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-3xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Data Dictionary
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          Every table that backs this site, where its data comes from, and its known
          quirks — the gaps and inconsistencies real data always has, stated plainly
          rather than smoothed over.
        </p>

        <div className="mt-10 space-y-10">
          {TABLES.map((table) => (
            <section key={table.name}>
              <h2 className="font-mono text-lg font-semibold text-black dark:text-zinc-50">
                {table.name}
              </h2>
              <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                {table.description}
              </p>
              {table.columns.length > 0 && (
                <div className="mt-3 space-y-2">
                  {table.columns.map((col) => (
                    <div key={col.name} className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="font-mono text-sm font-medium text-black dark:text-zinc-50">
                          {col.name}
                        </span>
                        <span className="text-xs text-zinc-500">{col.type}</span>
                      </div>
                      {col.note && (
                        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{col.note}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>

        <a href="/how-it-works" className="mt-10 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
          How it works &rarr;
        </a>
      </main>
    </div>
  );
}
