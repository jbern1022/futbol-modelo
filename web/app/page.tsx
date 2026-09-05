import FixtureList from "./fixture-list";

// Without this, Next.js statically prerenders this page at `docker
// build` time on docker-host -- which has no network route to the
// cluster-internal API_URL. A build-time fetch failure would get
// permanently baked into the deployed image as this page's ISR
// baseline (real incident, 2026-08-29: this exact thing happened,
// serving a dead "could not reach the API" page from every fresh pod
// until first successful runtime revalidation). Forcing dynamic
// rendering keeps this page server-rendered per real request instead,
// where the internal API is actually reachable -- the underlying
// fetch()'s own `next: { revalidate }` caching below still works fine
// on a dynamically-rendered route; only the route's own static HTML
// generation is disabled.
export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Fixture {
  match_id: number;
  league: string;
  season: string;
  home: string;
  away: string;
  kickoff_utc: string;
  status: string;
  home_score: number | null;
  away_score: number | null;
  n_predictions: number;
  headline_statement: string | null;
  headline_probability: number | null;
}

interface FixturesResponse {
  count: number;
  fixtures: Fixture[];
}

// Predictions are immutable once locked and grades are append-only, so
// the last successful response is always a safe thing to keep showing
// -- an outage should degrade to "data from 2h ago," not an empty page
// with a red error box. Module-level, so it survives across requests
// for the lifetime of this server process (resets on redeploy, which
// is fine -- a fresh pod fetching fresh data is the normal case this
// exists to cover the *absence* of).
let lastGood: { data: FixturesResponse; fetchedAt: number } | null = null;

async function getFixtures(): Promise<{ data: FixturesResponse | null; stale: boolean; fetchedAt: number | null }> {
  try {
    // Fixtures/headline predictions only change on the once-a-day
    // pipeline run -- an hour-old page view is still fully current.
    const res = await fetch(`${API_URL}/v1/fixtures?days=21`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    const data: FixturesResponse = await res.json();
    lastGood = { data, fetchedAt: Date.now() };
    return { data, stale: false, fetchedAt: lastGood.fetchedAt };
  } catch {
    if (lastGood) return { data: lastGood.data, stale: true, fetchedAt: lastGood.fetchedAt };
    return { data: null, stale: false, fetchedAt: null };
  }
}

function timeAgo(ms: number): string {
  const mins = Math.floor((Date.now() - ms) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default async function Home() {
  const { data, stale, fetchedAt } = await getFixtures();

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
            <a href="/lessons-learned" className="rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
              Lessons Learned
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

        {data && stale && fetchedAt && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Showing data from {timeAgo(fetchedAt)} — the API is temporarily
            unreachable. Predictions are locked before kickoff and grades are
            permanent, so nothing below has changed since then.
          </div>
        )}

        {data && data.fixtures.length === 0 && (
          <div className="mt-10 text-zinc-500">
            No upcoming fixtures in the next 21 days.
          </div>
        )}

        {data && data.fixtures.length > 0 && <FixtureList fixtures={data.fixtures} />}
      </main>
    </div>
  );
}
