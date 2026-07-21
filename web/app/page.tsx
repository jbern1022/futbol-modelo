const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Fixture {
  match_id: number;
  league: string;
  season: string;
  home: string;
  away: string;
  kickoff_utc: string;
  status: string;
  home_goals: number | null;
  away_goals: number | null;
  n_predictions: number;
}

interface FixturesResponse {
  count: number;
  fixtures: Fixture[];
}

async function getFixtures(): Promise<FixturesResponse | null> {
  try {
    const res = await fetch(`${API_URL}/fixtures?days=21`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

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

export default async function Home() {
  const data = await getFixtures();

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-4xl px-6 py-16">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
            Futbol Modelo
          </h1>
          <div className="flex gap-2">
            <a href="/petey" className="rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
              Ask Petey
            </a>
            <a href="/how-it-works" className="rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
              How It Works
            </a>
            <a href="/track-record" className="rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
              Track Record
            </a>
          </div>
        </div>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Calibrated soccer predictions across MLS, the Premier League, Serie A, and La Liga — generated and graded automatically, with every prediction locked before kickoff.
        </p>

        {!data && (
          <div className="mt-10 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            Could not reach the API at{" "}
            <code className="font-mono">{API_URL}</code>. Make sure the
            FastAPI backend is running.
          </div>
        )}

        {data && data.fixtures.length === 0 && (
          <div className="mt-10 text-zinc-500">
            No upcoming fixtures in the next 21 days.
          </div>
        )}

        {data && data.fixtures.length > 0 && (
          <div className="mt-10 space-y-3">
            {data.fixtures.map((f) => (
              <a key={f.match_id} href={`/fixtures/${f.match_id}`} className="block rounded-lg border border-zinc-200 bg-white p-4 transition-colors hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700">
                <div className="flex items-center justify-between">
                  <div>
                    {leagueBadge(f.league)}
                    <div className="mt-1 text-lg font-medium text-black dark:text-zinc-50">
                      {f.home} vs {f.away}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-zinc-500">
                      {new Date(f.kickoff_utc).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </div>
                    <div className="mt-1 text-xs text-zinc-400">
                      {f.n_predictions} predictions
                    </div>
                  </div>
                </div>
              </a>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
