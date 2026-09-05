import type { Metadata } from "next";
import Link from "next/link";
import { marketLabel } from "@/lib/markets";
import { plainOdds } from "@/lib/format";
import { leagueBadge, cleanStatement, outcomeBadge, roleBadge, whyPanel } from "@/lib/prediction-display";
import { LocalDate } from "../../local-date";

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
  context: Record<string, number> | null;
}

interface SlateResponse {
  fixture: {
    match_id: number;
    league: string;
    home: string;
    away: string;
    kickoff_utc: string;
    status: string;
  };
  predictions: Prediction[];
}

async function getSlate(matchId: string): Promise<SlateResponse | null> {
  try {
    // Predictions lock before kickoff and grades land once a night --
    // an hour-old cache never shows genuinely stale data.
    const res = await fetch(`${API_URL}/v1/fixtures/${matchId}/slate`, {
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
  params: Promise<{ matchId: string }>;
}): Promise<Metadata> {
  const { matchId } = await params;
  const data = await getSlate(matchId);
  if (!data) return { title: "Fixture not found — Futbol Modelo" };

  const { home, away, league } = data.fixture;
  const title = `${home} vs ${away} — Futbol Modelo`;
  const description = `Calibrated ${league} predictions for ${home} vs ${away}, locked before kickoff and graded automatically.`;

  return {
    title,
    description,
    openGraph: { title, description },
    twitter: { title, description },
  };
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
        <main className="mx-auto max-w-3xl px-6 py-16">
          <Link href="/" className="text-sm text-zinc-500 hover:underline">
            &larr; Back to fixtures
          </Link>
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

  const schemaOrgEvent = {
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    name: `${fixture.home} vs ${fixture.away}`,
    startDate: fixture.kickoff_utc,
    eventStatus: "https://schema.org/EventScheduled",
    competitor: [{ "@type": "SportsTeam", name: fixture.home }, { "@type": "SportsTeam", name: fixture.away }],
    homeTeam: { "@type": "SportsTeam", name: fixture.home },
    awayTeam: { "@type": "SportsTeam", name: fixture.away },
  };

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(schemaOrgEvent) }}
      />
      <main className="mx-auto max-w-3xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <div className="mt-6 flex items-start justify-between">
          <div>
            <span className="flex items-center gap-2">
              {leagueBadge(fixture.league)}
              <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                {fixture.status}
              </span>
            </span>
            <h1 className="mt-1 text-2xl font-semibold text-black dark:text-zinc-50">
              {fixture.home} vs {fixture.away}
            </h1>
            <p className="mt-1 text-zinc-500">
              <LocalDate
                date={fixture.kickoff_utc}
                mode="datetime"
                options={{ dateStyle: "full", timeStyle: "short" }}
              />{" "}
              <span className="text-xs">(your local time)</span>
            </p>
          </div>
          <a href={`/petey?mode=form&league=${encodeURIComponent(fixture.league)}&team=${encodeURIComponent(fixture.home)}`} className="whitespace-nowrap rounded-md border border-zinc-200 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            Ask Petey
          </a>
        </div>

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
                  .map((p) => (
                    <div key={p.prediction_id} className="flex items-start justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900">
                      <div className="text-black dark:text-zinc-50">
                        {cleanStatement(p)}
                        {roleBadge(p.probability)}
                        {outcomeBadge(p.outcome)}
                        {whyPanel(p.context)}
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-semibold text-black dark:text-zinc-50">
                          {(p.probability * 100).toFixed(1)}%
                        </div>
                        <div className="text-xs text-zinc-500">{plainOdds(p.probability)}</div>
                        <Link
                          href={`/prediction/${p.prediction_id}`}
                          className="mt-1 inline-block text-xs text-zinc-400 hover:text-zinc-600 hover:underline dark:hover:text-zinc-300"
                        >
                          Permalink
                        </Link>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
