const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Prediction {
  prediction_id: number;
  market: string;
  statement: string;
  side: string;
  line: number | null;
  probability: number;
  locked_at: string;
  subject_team: string | null;
  subject_player: string | null;
  outcome: string | null;
  actual_value: number | null;
}

interface SlateResponse {
  fixture: {
    match_id: number;
    league: string;
    home: string;
    away: string;
    kickoff_utc: string;
    status: string;
    home_goals: number | null;
    away_goals: number | null;
  };
  predictions: Prediction[];
}

const MARKET_LABELS: Record<string, string> = {
  "1X2": "Match Result",
  BTTS: "Both Teams to Score",
  TOTAL_GOALS: "Total Goals",
  CORNERS: "Corners",
  SOT: "Shots on Target",
  PLAYER_GOALS: "Anytime Goalscorer",
  PLAYER_SAVES: "Goalkeeper Saves",
};

const LEAGUE_COLORS: Record<string, string> = {
  MLS: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  EPL: "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300",
  SERIE_A: "bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300",
  LA_LIGA: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  WC: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
};

function leagueBadge(league: string) {
  const style = LEAGUE_COLORS[league] || "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${style}`}>
      {league}
    </span>
  );
}

function marketLabel(market: string): string {
  return MARKET_LABELS[market] || market;
}

// Legacy statements were written as "Corners over 4.5" / "Sot over 3.5" — no
// team, and an abbreviation. Statements are immutable, so historical rows can
// never be rewritten; they are repaired for display only. New rows are written
// with the subject baked in (see scripts/generate_slate.py).
function cleanStatement(statement: string): string {
  return statement.replace(/^Sot\b/i, "Shots on target");
}

// Without this, the two sides of a corners market render identically: the
// ledger row says "Corners over 4.5" for both home and away.
function displayStatement(p: Prediction): string {
  const base = cleanStatement(p.statement);
  const subject = p.subject_team ?? p.subject_player;
  if (!subject) return base;
  if (base.toLowerCase().includes(subject.toLowerCase())) return base;
  return `${subject} — ${base}`;
}

// How far ahead of kickoff the prediction was locked. Returns null when it
// cannot be computed, in which case the caller shows the raw timestamp.
function lockLead(lockedAt: string, kickoff: string): string | null {
  const ms = new Date(kickoff).getTime() - new Date(lockedAt).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const minutes = Math.floor(ms / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-3 w-3 shrink-0"
         fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="10" width="16" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

async function getSlate(matchId: string): Promise<SlateResponse | null> {
  try {
    const res = await fetch(`${API_URL}/fixtures/${matchId}/slate`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

function outcomeBadge(outcome: string | null) {
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

export default async function FixturePage({
  params,
}: {
  params: Promise<{ matchId: string }>;
}) {
  const { matchId } = await params;
  const data = await getSlate(matchId);

  if (!data) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-black">
        <main className="mx-auto max-w-3xl px-6 py-12">
          <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            Fixture not found, or the API is unreachable.
          </div>
        </main>
      </div>
    );
  }

  const { fixture, predictions } = data;

  const grouped = predictions.reduce<Record<string, Prediction[]>>((acc, p) => {
    (acc[p.market] ??= []).push(p);
    return acc;
  }, {});
  const marketOrder = ["1X2", "BTTS", "TOTAL_GOALS", "CORNERS", "SOT",
                       "PLAYER_GOALS", "PLAYER_SAVES"];
  const orderedMarkets = Object.keys(grouped).sort(
    (a, b) => marketOrder.indexOf(a) - marketOrder.indexOf(b)
  );

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-3xl px-6 py-12">

        <div className="mt-6 flex items-start justify-between">
          <div>
            <span className="flex items-center gap-2">
              {leagueBadge(fixture.league)}
              <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                {fixture.status}
              </span>
            </span>
            <h1 className="mt-1 text-2xl font-semibold text-black dark:text-zinc-50">
              {fixture.home}{" "}
              {fixture.home_goals !== null && fixture.away_goals !== null ? (
                <span className="tabular-nums">
                  {fixture.home_goals}&ndash;{fixture.away_goals}
                </span>
              ) : (
                <span className="text-zinc-400">vs</span>
              )}{" "}
              {fixture.away}
            </h1>
            <p className="mt-1 text-zinc-500">
              {new Date(fixture.kickoff_utc).toLocaleString(undefined, {
                dateStyle: "full",
                timeStyle: "short",
              })}
            </p>
          </div>
          <a href={`/petey?mode=form&league=${encodeURIComponent(fixture.league)}&team=${encodeURIComponent(fixture.home)}`} className="whitespace-nowrap rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            Ask Petey
          </a>
        </div>

        {predictions.length > 0 && (
          <p className="mt-6 flex items-center gap-1.5 text-xs text-zinc-500">
            <LockIcon />
            Every prediction below was written to an append-only ledger before
            kickoff. Once written, none of them can be edited or deleted.
          </p>
        )}

        <div className="mt-8 space-y-6">
          {predictions.length === 0 && (
            <p className="text-zinc-500">No predictions logged yet.</p>
          )}
          {orderedMarkets.map((market) => (
            <div key={market}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
                {marketLabel(market)}
              </h2>
              <div className="space-y-2">
                {grouped[market]
                  .slice()
                  .sort((a, b) => b.probability - a.probability)
                  .map((p) => {
                    const lead = lockLead(p.locked_at, fixture.kickoff_utc);
                    return (
                      <div key={p.prediction_id} className="flex items-start justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900">
                        <div className="min-w-0">
                          <div className="text-black dark:text-zinc-50">
                            {displayStatement(p)}
                            {outcomeBadge(p.outcome)}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-400 dark:text-zinc-500">
                            <span className="inline-flex items-center gap-1"
                                  title={`Locked at ${new Date(p.locked_at).toISOString()}`}>
                              <LockIcon />
                              {lead
                                ? `Locked ${lead} before kickoff`
                                : `Locked ${new Date(p.locked_at).toLocaleString()}`}
                            </span>
                            {p.actual_value !== null && (
                              <span>&middot; actual: {p.actual_value}</span>
                            )}
                          </div>
                        </div>
                        <div className="shrink-0 text-lg font-semibold text-black dark:text-zinc-50">
                          {(p.probability * 100).toFixed(1)}%
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
