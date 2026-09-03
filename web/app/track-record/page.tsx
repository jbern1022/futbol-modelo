import Link from "next/link";
import TrackRecordContent from "./track-record-content";

// See web/app/page.tsx's identical comment -- without this, Next.js
// statically prerenders this page at docker-host build time, which
// has no network route to the cluster-internal API_URL, baking a dead
// empty-data page into the deployed image.
export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ScorecardRow {
  league: string;
  season: string;
  market: string;
  n_predictions: number;
  hit_rate: number;
  avg_confidence: number;
  brier: number;
  log_loss: number;
}

interface CalibrationRow {
  league: string;
  market: string;
  side: string;
  avg_stated_prob: number;
  realized_rate: number;
  n: number;
}

async function getScorecard(): Promise<ScorecardRow[]> {
  try {
    // The API itself already caches this for 5 minutes; an hour here
    // cuts requests reaching the API pod at all, not just its DB load.
    const res = await fetch(`${API_URL}/v1/scorecard`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.scorecard || [];
  } catch {
    return [];
  }
}

async function getCalibration(): Promise<CalibrationRow[]> {
  try {
    const res = await fetch(`${API_URL}/v1/calibration`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.calibration || [];
  } catch {
    return [];
  }
}

export default async function TrackRecordPage() {
  const [scorecard, calibration] = await Promise.all([
    getScorecard(),
    getCalibration(),
  ]);

  const totalGraded = scorecard.length > 0;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-4xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <div className="mt-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
              Track Record
            </h1>
            <p className="mt-2 max-w-2xl text-zinc-600 dark:text-zinc-400">
              Every prediction is locked before kickoff and graded automatically once
              the match finishes. This page shows the honest, unfiltered record —
              including the misses.
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Link
              href="/misses"
              className="whitespace-nowrap rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              Biggest Misses
            </Link>
            <a
              href="/api/export"
              className="whitespace-nowrap rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              Download CSV
            </a>
          </div>
        </div>

        {!totalGraded && (
          <div className="mt-10 rounded-lg border border-zinc-200 bg-white p-6 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            No graded predictions yet — check back once matches have been played.
          </div>
        )}

        {totalGraded && <TrackRecordContent scorecard={scorecard} calibration={calibration} />}
      </main>
    </div>
  );
}
