import Link from "next/link";
import { marketLabel } from "@/lib/markets";
import { leagueBadge, cleanStatement } from "@/lib/prediction-display";
import { LocalDate } from "../local-date";

// See web/app/page.tsx's identical comment -- without this, Next.js
// statically prerenders this page at docker-host build time, which
// has no network route to the cluster-internal API_URL, baking a dead
// empty-data page into the deployed image.
export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Miss {
  prediction_id: number;
  market: string;
  statement: string;
  side: string;
  probability: number;
  locked_at: string;
  actual_value: number | null;
  subject_team: string | null;
  subject_player: string | null;
  match_id: number;
  league: string;
  home: string;
  away: string;
  kickoff_utc: string;
}

async function getMisses(): Promise<Miss[]> {
  try {
    // Grading runs once a night -- an hour-old list is still current.
    const res = await fetch(`${API_URL}/v1/misses?limit=30`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.misses || [];
  } catch {
    return [];
  }
}

export default async function MissesPage() {
  const misses = await getMisses();

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/track-record" className="text-sm text-zinc-500 hover:underline">
          &larr; Track Record
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Biggest Misses
        </h1>
        <p className="mt-2 max-w-xl text-zinc-600 dark:text-zinc-400">
          Every prediction is graded and published either way. These are the
          highest-confidence calls that missed — the honest counterpart to
          only ever showing hits.
        </p>

        {misses.length === 0 ? (
          <div className="mt-10 rounded-lg border border-zinc-200 bg-white p-6 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            No misses recorded (yet).
          </div>
        ) : (
          <div className="mt-8 space-y-3">
            {misses.map((p) => (
              <Link
                key={p.prediction_id}
                href={`/prediction/${p.prediction_id}`}
                className="block rounded-lg border border-zinc-200 bg-white p-4 transition-colors hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      {leagueBadge(p.league)}
                      <span className="text-xs uppercase tracking-wide text-zinc-500">
                        {marketLabel(p.market)}
                      </span>
                    </div>
                    <div className="mt-1 text-black dark:text-zinc-50">{cleanStatement(p)}</div>
                    <div className="mt-0.5 text-xs text-zinc-500">
                      {p.home} vs {p.away} &middot;{" "}
                      <LocalDate
                        date={p.kickoff_utc}
                        options={{ month: "short", day: "numeric", year: "numeric" }}
                      />
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-semibold text-red-600 dark:text-red-400">
                      {(p.probability * 100).toFixed(1)}%
                    </div>
                    {p.actual_value !== null && (
                      <div className="text-xs text-zinc-500">actual: {p.actual_value}</div>
                    )}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
