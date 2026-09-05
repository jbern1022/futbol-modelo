import { marketLabel } from "@/lib/markets";
import { cleanStatement } from "@/lib/prediction-display";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const BASE_URL = "https://futbol.josephbernal.com";
const FEED_SIZE = 50;

interface FeedPrediction {
  prediction_id: number;
  market: string;
  statement: string;
  side: string | null;
  probability: number;
  outcome: string;
  actual_value: number | null;
  subject_team: string | null;
  league: string;
  home: string;
  away: string;
  kickoff_utc: string;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

async function getRecentlyGraded(): Promise<FeedPrediction[]> {
  try {
    // Grading runs once a night -- feed readers polling hourly won't
    // ever see stale results.
    const res = await fetch(`${API_URL}/v1/predictions?limit=${FEED_SIZE}`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.predictions || [];
  } catch {
    return [];
  }
}

export async function GET() {
  const predictions = await getRecentlyGraded();

  const items = predictions
    .map((p) => {
      const link = `${BASE_URL}/prediction/${p.prediction_id}`;
      const title = `${p.outcome === "hit" ? "✓" : "✗"} ${cleanStatement(p)} — ${marketLabel(p.market)}`;
      const description = [
        `${p.home} vs ${p.away} (${p.league})`,
        `Stated: ${(p.probability * 100).toFixed(1)}%`,
        p.actual_value !== null ? `Actual: ${p.actual_value}` : null,
        `Outcome: ${p.outcome}`,
      ]
        .filter(Boolean)
        .join(" · ");
      return `
    <item>
      <title>${escapeXml(title)}</title>
      <link>${link}</link>
      <guid isPermaLink="true">${link}</guid>
      <description>${escapeXml(description)}</description>
      <pubDate>${new Date(p.kickoff_utc).toUTCString()}</pubDate>
    </item>`;
    })
    .join("");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Futbol Modelo — Graded Predictions</title>
    <link>${BASE_URL}/track-record</link>
    <description>Every graded prediction from Futbol Modelo's calibrated soccer prediction system — hits and misses alike, published either way.</description>
    <language>en-us</language>
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="${BASE_URL}/feed.xml" rel="self" type="application/rss+xml" />${items}
  </channel>
</rss>`;

  return new Response(xml, {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" },
  });
}
