import Link from "next/link";
import { plainOdds } from "@/lib/format";
import { marketLabel } from "@/lib/markets";
import { leagueBadge, cleanStatement, outcomeBadge, roleBadge, whyPanel } from "@/lib/prediction-display";
import { LocalDate } from "../../local-date";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PredictionDetail {
  prediction_id: number;
  market: string;
  statement: string;
  side: string;
  line: number | null;
  probability: number;
  locked_at: string;
  created_at: string;
  context: Record<string, number> | null;
  subject_team: string | null;
  subject_player: string | null;
  outcome: string | null;
  actual_value: number | null;
  graded_at: string | null;
  model_name: string;
  version_tag: string;
  trained_at: string;
  match_id: number;
  league: string;
  home: string;
  away: string;
  kickoff_utc: string;
  status: string;
}

async function getPrediction(id: string): Promise<PredictionDetail | null> {
  try {
    // A prediction only ever changes once, when it's graded (once a
    // night) -- an hour-old cache is never meaningfully stale.
    const res = await fetch(`${API_URL}/v1/predictions/${id}`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function PredictionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const p = await getPrediction(id);

  if (!p) {
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-black">
        <main className="mx-auto max-w-2xl px-6 py-16">
          <Link href="/" className="text-sm text-zinc-500 hover:underline">
            &larr; Back to fixtures
          </Link>
          <h1 className="mt-6 text-2xl font-semibold text-black dark:text-zinc-50">
            Prediction not found
          </h1>
          <p className="mt-2 text-zinc-500">
            This prediction doesn&apos;t exist, or the link is out of date.
          </p>
        </main>
      </div>
    );
  }

  const schemaOrgClaim = {
    "@context": "https://schema.org",
    "@type": "ClaimReview",
    claimReviewed: cleanStatement(p),
    datePublished: p.locked_at,
    reviewRating: {
      "@type": "Rating",
      ratingValue: (p.probability * 100).toFixed(1),
      bestRating: "100",
      worstRating: "0",
    },
  };

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(schemaOrgClaim) }}
      />
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href={`/fixtures/${p.match_id}`} className="text-sm text-zinc-500 hover:underline">
          &larr; {p.home} vs {p.away}
        </Link>

        <div className="mt-6 flex items-center gap-2">
          {leagueBadge(p.league)}
          <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
            {marketLabel(p.market)}
          </span>
        </div>

        <h1 className="mt-2 text-2xl font-semibold text-black dark:text-zinc-50">
          {cleanStatement(p)}
          {roleBadge(p.probability)}
          {outcomeBadge(p.outcome)}
        </h1>

        <div className="mt-6 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-zinc-500">Stated probability</span>
            <div className="text-right">
              <div className="text-3xl font-semibold text-black dark:text-zinc-50">
                {(p.probability * 100).toFixed(1)}%
              </div>
              <div className="text-xs text-zinc-500">{plainOdds(p.probability)}</div>
            </div>
          </div>
          {p.outcome && p.outcome !== "void" && (
            <div className="mt-4 flex items-baseline justify-between border-t border-zinc-100 pt-4 dark:border-zinc-800">
              <span className="text-sm text-zinc-500">Actual result</span>
              <span className="text-black dark:text-zinc-50">
                {p.outcome === "hit" ? "Hit" : "Miss"}
                {p.actual_value !== null && ` (${p.actual_value})`}
              </span>
            </div>
          )}
          {whyPanel(p.context)}
        </div>

        <dl className="mt-8 space-y-3 text-sm">
          <div className="flex justify-between border-b border-zinc-200 pb-2 dark:border-zinc-800">
            <dt className="text-zinc-500">Fixture</dt>
            <dd className="text-black dark:text-zinc-50">
              <Link href={`/fixtures/${p.match_id}`} className="hover:underline">
                {p.home} vs {p.away}
              </Link>
            </dd>
          </div>
          <div className="flex justify-between border-b border-zinc-200 pb-2 dark:border-zinc-800">
            <dt className="text-zinc-500">Kickoff</dt>
            <dd className="text-black dark:text-zinc-50">
              <LocalDate date={p.kickoff_utc} mode="datetime" options={{ dateStyle: "full", timeStyle: "short" }} />
            </dd>
          </div>
          <div className="flex justify-between border-b border-zinc-200 pb-2 dark:border-zinc-800">
            <dt className="text-zinc-500">Locked at</dt>
            <dd className="text-black dark:text-zinc-50">
              <LocalDate date={p.locked_at} mode="datetime" options={{ dateStyle: "medium", timeStyle: "short" }} />
            </dd>
          </div>
          {p.graded_at && (
            <div className="flex justify-between border-b border-zinc-200 pb-2 dark:border-zinc-800">
              <dt className="text-zinc-500">Graded at</dt>
              <dd className="text-black dark:text-zinc-50">
                <LocalDate date={p.graded_at} mode="datetime" options={{ dateStyle: "medium", timeStyle: "short" }} />
              </dd>
            </div>
          )}
          <div className="flex justify-between border-b border-zinc-200 pb-2 dark:border-zinc-800">
            <dt className="text-zinc-500">Model</dt>
            <dd className="text-black dark:text-zinc-50">
              {p.model_name} <span className="text-zinc-500">({p.version_tag})</span>
            </dd>
          </div>
          <div className="flex justify-between pb-2">
            <dt className="text-zinc-500">Prediction ID</dt>
            <dd className="text-black dark:text-zinc-50">#{p.prediction_id}</dd>
          </div>
        </dl>
      </main>
    </div>
  );
}
