import type { Metadata } from "next";
import Link from "next/link";
import { leagueBadge } from "@/lib/prediction-display";
import { LocalDate } from "../../local-date";
import PredictionLog from "../../track-record/prediction-log";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface TeamFixtureRow {
  match_id: number;
  league: string;
  opponent: string;
  is_home: boolean;
  kickoff_utc: string;
  status: string;
  team_score: number | null;
  opponent_score: number | null;
}

interface TeamDetail {
  team: string;
  leagues: string[];
  upcoming: TeamFixtureRow[];
  recent: TeamFixtureRow[];
}

async function getTeam(name: string): Promise<TeamDetail | null> {
  try {
    // Fixture history only changes on the once-a-day pipeline run, same
    // as the homepage's own fixtures fetch.
    const res = await fetch(`${API_URL}/v1/teams/${encodeURIComponent(name)}`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ name: string }>;
}): Promise<Metadata> {
  const { name } = await params;
  const team = decodeURIComponent(name);
  const title = `${team} — Futbol Modelo`;
  const description = `Fixture history and every graded prediction for ${team}.`;
  return { title, description, openGraph: { title, description }, twitter: { title, description } };
}

// W/D/L is the standard shorthand everywhere else this project could
// plausibly point at (Track Record, fixture cards) -- not introducing
// a new convention just for this page.
function resultLetter(row: TeamFixtureRow): { letter: string; className: string } {
  if (row.team_score === null || row.opponent_score === null) {
    return { letter: "?", className: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800" };
  }
  if (row.team_score > row.opponent_score) {
    return { letter: "W", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" };
  }
  if (row.team_score < row.opponent_score) {
    return { letter: "L", className: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300" };
  }
  return { letter: "D", className: "bg-zinc-200 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200" };
}

function FixtureRow({ row, showScore }: { row: TeamFixtureRow; showScore: boolean }) {
  const result = showScore ? resultLetter(row) : null;
  return (
    <Link
      href={`/fixtures/${row.match_id}`}
      className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-2.5 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:bg-zinc-800"
    >
      <div className="flex min-w-0 items-center gap-2">
        {result && (
          <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-xs font-semibold ${result.className}`}>
            {result.letter}
          </span>
        )}
        {leagueBadge(row.league)}
        <span className="truncate text-black dark:text-zinc-50">
          {row.is_home ? "vs" : "@"} {row.opponent}
        </span>
      </div>
      <div className="shrink-0 text-right text-sm text-zinc-500">
        {showScore && row.team_score !== null ? (
          <span className="font-medium text-black dark:text-zinc-50">
            {row.team_score}&ndash;{row.opponent_score}
          </span>
        ) : (
          <LocalDate date={row.kickoff_utc} options={{ month: "short", day: "numeric" }} />
        )}
      </div>
    </Link>
  );
}

export default async function TeamPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  const team = await getTeam(decodeURIComponent(name));

  if (!team) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-black">
        <main className="mx-auto max-w-3xl px-6 py-16">
          <Link href="/" className="text-sm text-zinc-500 hover:underline">
            &larr; Back to fixtures
          </Link>
          <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            Team not found, or the API is unreachable.
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-3xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <div className="mt-6 flex items-center gap-2">
          {team.leagues.map((l) => (
            <span key={l}>{leagueBadge(l)}</span>
          ))}
        </div>
        <h1 className="mt-1 text-2xl font-semibold text-black dark:text-zinc-50">
          {team.team}
        </h1>

        {team.upcoming.length > 0 && (
          <>
            <h2 className="mt-8 text-lg font-semibold text-black dark:text-zinc-50">
              Upcoming
            </h2>
            <div className="mt-3 space-y-2">
              {team.upcoming.map((row) => (
                <FixtureRow key={row.match_id} row={row} showScore={false} />
              ))}
            </div>
          </>
        )}

        {team.recent.length > 0 && (
          <>
            <h2 className="mt-8 text-lg font-semibold text-black dark:text-zinc-50">
              Recent results
            </h2>
            <div className="mt-3 space-y-2">
              {team.recent.map((row) => (
                <FixtureRow key={row.match_id} row={row} showScore={true} />
              ))}
            </div>
          </>
        )}

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          Every graded prediction
        </h2>
        <PredictionLog league="" season="" market="" team={team.team} />
      </main>
    </div>
  );
}
