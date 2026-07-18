const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"\;

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
  avg_stated_prob: number;
  realized_rate: number;
  n: number;
}

const MARKET_LABELS: Record<string, string> = {
  "1X2": "Match Result",
  BTTS: "Both Teams to Score",
  TOTAL_GOALS: "Total Goals",
  CORNERS: "Corners",
  SOT: "Shots on Target",
  PLAYER_GOALS: "Anytime Goalscorer",
  PLAYER_SAVES: "Goalkeeper Saves",
};

function marketLabel(market: string): string {
  return MARKET_LABELS[market] || market;
}

async function getScorecard(): Promise<ScorecardRow[]> {
  try {
    const res = await fetch(`${API_URL}/scorecard`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = await res.json();
    return data.scorecard || [];
  } catch {
    return [];
  }
}

async function getCalibration(): Promise<CalibrationRow[]> {
  try {
    const res = await fetch(`${API_URL}/calibration`, { cache: "no-store" });
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

  const totalPredictions = scorecard.reduce((sum, r) => sum + r.n_predictions, 0);
  const totalGraded = scorecard.length > 0;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-4xl px-6 py-16">
        <a href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </a>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Track Record
        </h1>
        <p className="mt-2 max-w-2xl text-zinc-600 dark:text-zinc-400">
          Every prediction is locked before kickoff and graded automatically once
          the match finishes. This page shows the honest, unfiltered record —
          including the misses.
        </p>

        {!totalGraded && (
          <div className="mt-10 rounded-lg border border-zinc-200 bg-white p-6 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            No graded predictions yet — check back once matches have been played.
          </div>
        )}

        {totalGraded && (
          <>
            <div className="mt-8 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <span className="text-sm text-zinc-500">Total graded predictions</span>
              <div className="text-2xl font-semibold text-black dark:text-zinc-50">
                {totalPredictions.toLocaleString()}
              </div>
            </div>

            <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
              By market
            </h2>
            <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                  <tr>
                    <th className="px-4 py-2 font-medium">League</th>
                    <th className="px-4 py-2 font-medium">Market</th>
                    <th className="px-4 py-2 font-medium text-right">N</th>
                    <th className="px-4 py-2 font-medium text-right">Stated</th>
                    <th className="px-4 py-2 font-medium text-right">Realized</th>
                  </tr>
                </thead>
                <tbody>
                  {scorecard.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-zinc-100 last:border-0 dark:border-zinc-800"
                    >
                      <td className="px-4 py-2 text-zinc-500">{row.league}</td>
                      <td className="px-4 py-2 text-black dark:text-zinc-50">
                        {marketLabel(row.market)}
                      </td>
                      <td className="px-4 py-2 text-right text-zinc-500">
                        {row.n_predictions}
                      </td>
                      <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                        {(row.avg_confidence * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                        {(row.hit_rate * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {calibration.length > 0 && (
              <>
                <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
                  Calibration
                </h2>
                <p className="mt-1 text-sm text-zinc-500">
                  A well-calibrated model's stated confidence should roughly match
                  how often it's actually right. The bars below compare the two —
                  the closer they are, the more trustworthy the probabilities.
                </p>
                <div className="mt-4 space-y-3">
                  {calibration.map((row, i) => (
                    <div key={i} className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-black dark:text-zinc-50">
                          {marketLabel(row.market)}{" "}
                          <span className="text-zinc-500">({row.league}, n={row.n})</span>
                        </span>
                      </div>
                      <div className="mt-2 space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="w-16 text-xs text-zinc-500">Stated</span>
                          <div className="h-2 flex-1 rounded-full bg-zinc-100 dark:bg-zinc-800">
                            <div
                              className="h-2 rounded-full bg-zinc-400"
                              style={{ width: `${row.avg_stated_prob * 100}%` }}
                            />
                          </div>
                          <span className="w-12 text-right text-xs text-zinc-500">
                            {(row.avg_stated_prob * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="w-16 text-xs text-zinc-500">Realized</span>
                          <div className="h-2 flex-1 rounded-full bg-zinc-100 dark:bg-zinc-800">
                            <div
                              className="h-2 rounded-full bg-emerald-500"
                              style={{ width: `${row.realized_rate * 100}%` }}
                            />
                          </div>
                          <span className="w-12 text-right text-xs text-zinc-500">
                            {(row.realized_rate * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
