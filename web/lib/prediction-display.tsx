// Shared display helpers for anywhere a single prediction gets rendered
// (the fixture slate page, the per-prediction permalink page). Extracted
// so the two don't drift out of sync the way two separate CalibrationRow
// interfaces did earlier -- one update here, both pages stay consistent.

export interface PredictionLike {
  market: string;
  statement: string;
  side: string;
  probability: number;
  subject_team: string | null;
  outcome: string | null;
  context: Record<string, number> | null;
}

export const LEAGUE_COLORS: Record<string, string> = {
  MLS: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  EPL: "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300",
  SERIE_A: "bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300",
  LA_LIGA: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  WC: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
};

export function leagueBadge(league: string) {
  const style = LEAGUE_COLORS[league] || "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${style}`}>
      {league}
    </span>
  );
}

export function cleanStatement(p: Pick<PredictionLike, "market" | "statement" | "subject_team">): string {
  let text = p.statement.replace(/^Sot\b/i, "Shots on target");
  if (p.subject_team && (p.market === "CORNERS" || p.market === "SOT")) {
    // Predictions written before the team-name prefix landed have no
    // "Team — " in the ledger text (immutable, can't be backfilled) --
    // strip whatever prefix is there, if any, and rebuild from the
    // API's resolved subject_team so old and new rows render the same.
    const dashIdx = text.indexOf(" — ");
    if (dashIdx !== -1) {
      text = text.slice(dashIdx + 3);
    }
    text = `${p.subject_team} — ${text}`;
  }
  return text;
}

export function outcomeBadge(outcome: string | null) {
  if (!outcome) return null;
  const styles: Record<string, string> = {
    hit: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
    miss: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
    void: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  };
  return (
    <span className={`ml-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${styles[outcome] || styles.void}`}>
      {outcome}
    </span>
  );
}

// Mirrors build_slate()'s own selection bands in src/predictions/generator.py
// (TARGET_BAND = 0.60-0.75, anchors > 0.80, specs < 0.45) -- purely a
// display label, derived from probability, not a stored field.
export function roleBadge(probability: number) {
  let label: string | null = null;
  if (probability > 0.8) label = "Anchor";
  else if (probability >= 0.6 && probability <= 0.75) label = "Bold pick";
  else if (probability < 0.45) label = "Long shot";
  if (!label) return null;
  return (
    <span className="ml-2 rounded bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
      {label}
    </span>
  );
}

// current_form()/player-form's raw feature keys, in src/predictions/generator.py
// terms -- rendered as the "why" panel. Falls back to a humanized version
// of any key not listed here rather than hiding it.
const CONTEXT_LABELS: Record<string, string> = {
  corners_for_r5: "Corners for (last 5)",
  corners_against_r5: "Corners against (last 5)",
  shots_for_r5: "Shots for (last 5)",
  shots_against_r5: "Shots against (last 5)",
  sot_for_r5: "Shots on target for (last 5)",
  sot_against_r5: "Shots on target against (last 5)",
  xg_for_r5: "xG for (last 5)",
  xg_against_r5: "xG against (last 5)",
  rest_days: "Rest days",
  is_home: "Home game",
  p_shots_r5: "Player shots (last 5)",
  p_minutes_r5: "Player minutes (last 5)",
  p_goals_r10: "Player goals (last 10)",
  p_key_passes_r5: "Player key passes (last 5)",
  p_saves_r5: "Player saves (last 5)",
};

function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export function whyPanel(context: Record<string, number> | null) {
  if (!context) return null;
  const entries = Object.entries(context).filter(([, v]) => v !== null);
  if (entries.length === 0) return null;
  return (
    <details className="mt-2 text-xs text-zinc-500">
      <summary className="cursor-pointer select-none hover:text-zinc-700 dark:hover:text-zinc-300">
        Why
      </summary>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {entries.map(([key, value]) => (
          <div key={key} className="flex justify-between gap-2">
            <dt>{CONTEXT_LABELS[key] ?? humanizeKey(key)}</dt>
            <dd className="text-zinc-700 dark:text-zinc-300">
              {typeof value === "number" ? value.toFixed(key === "rest_days" ? 0 : 2) : String(value)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
