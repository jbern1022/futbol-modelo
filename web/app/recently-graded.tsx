import Link from "next/link";
import { leagueBadge, cleanStatement, outcomeBadge } from "@/lib/prediction-display";
import { LocalDate } from "./local-date";

interface RecentlyGradedRow {
  prediction_id: number;
  market: string;
  statement: string;
  side: string;
  probability: number;
  outcome: string;
  subject_team: string | null;
  league: string;
  home: string;
  away: string;
  graded_at: string;
}

export default function RecentlyGraded({ predictions }: { predictions: RecentlyGradedRow[] }) {
  if (predictions.length === 0) return null;

  return (
    <>
      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
        Recently graded
      </h2>
      <p className="mt-1 text-sm text-zinc-500">
        Locked before kickoff, graded automatically once the match finished.
      </p>
      <div className="mt-4 space-y-2">
        {predictions.map((p) => (
          <Link
            key={p.prediction_id}
            href={`/prediction/${p.prediction_id}`}
            className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:bg-zinc-800"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                {leagueBadge(p.league)}
                <span className="truncate text-sm text-zinc-500">
                  {p.home} vs {p.away}
                </span>
              </div>
              <div className="mt-0.5 truncate text-black dark:text-zinc-50">
                {cleanStatement(p)}
                {outcomeBadge(p.outcome)}
              </div>
            </div>
            <div className="shrink-0 text-right text-xs text-zinc-400">
              <LocalDate date={p.graded_at} options={{ month: "short", day: "numeric" }} />
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
