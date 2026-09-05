import { ImageResponse } from "next/og";

export const alt = "Match prediction";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SlatePrediction {
  market: string;
  statement: string;
  probability: number;
}

export default async function Image({
  params,
}: {
  params: Promise<{ matchId: string }>;
}) {
  const { matchId } = await params;

  let home = "TBD";
  let away = "TBD";
  let league = "";
  let headline: string | null = null;

  try {
    // Social crawlers hit this rarely and cache it themselves anyway;
    // an hour-old headline pick is never meaningfully stale.
    const res = await fetch(`${API_URL}/v1/fixtures/${matchId}/slate`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const data = await res.json();
      home = data.fixture?.home ?? home;
      away = data.fixture?.away ?? away;
      league = data.fixture?.league ?? "";
      // predictions arrive sorted by probability DESC, so the first 1X2
      // entry is already the highest-confidence one.
      const top = (data.predictions as SlatePrediction[] | undefined)?.find(
        (p) => p.market === "1X2"
      );
      if (top) headline = `${top.statement} — ${(top.probability * 100).toFixed(0)}%`;
    }
  } catch {
    // fall through to the TBD placeholders
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#09090b",
          color: "#fafafa",
          fontFamily: "sans-serif",
        }}
      >
        {league && (
          <div style={{ fontSize: 28, color: "#a1a1aa", textTransform: "uppercase", letterSpacing: 4 }}>
            {league}
          </div>
        )}
        <div style={{ display: "flex", fontSize: 64, fontWeight: 700, marginTop: 20 }}>
          {home} vs {away}
        </div>
        {headline && (
          <div style={{ fontSize: 36, marginTop: 32, color: "#4ade80" }}>{headline}</div>
        )}
        <div style={{ fontSize: 24, marginTop: 48, color: "#71717a" }}>Futbol Modelo</div>
      </div>
    ),
    { ...size }
  );
}
