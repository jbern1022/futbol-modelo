import { SmallSampleBadge, isSmallSample } from "../small-sample";

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

interface VoidRow {
  league: string;
  market: string;
  void_reason: string;
  n: number;
}

const VOID_REASON_LABELS: Record<string, string> = {
  player_absent: "player did not feature",
  stat_unavailable: "the statistic was never published",
  subject_missing: "prediction had no subject recorded",
  unspecified: "voided before reasons were recorded",
};

interface League {
  code: string;
  name: string;
  concluded: boolean;
  n_predictions: number;
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

async function getVoids(): Promise<VoidRow[]> {
  try {
    const res = await fetch(`${API_URL}/voids`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()).voids || [];
  } catch {
    return [];
  }
}

async function getLeagues(): Promise<League[]> {
  try {
    const res = await fetch(`${API_URL}/leagues`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()).leagues || [];
  } catch {
    return [];
  }
}

// A finished competition keeps every prediction it ever made and stays in the
// rates below. It is labelled, not removed: dropping a concluded competition
// from published figures would select the record on the basis of how it went.
function ConcludedBadge() {
  return (
    <span
      title="This competition has finished. Its predictions remain in the record."
      className="ml-1.5 inline-flex items-center rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
    >
      completed
    </span>
  );
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
  const [scorecard, calibration, leagues, voids] = await Promise.all([
    getScorecard(),
    getCalibration(),
    getLeagues(),
    getVoids(),
  ]);
  const voidsByReason = voids.reduce<Record<string, number>>((acc, v) => {
    acc[v.void_reason] = (acc[v.void_reason] || 0) + Number(v.n);
    return acc;
  }, {});
  const totalVoided = Object.values(voidsByReason).reduce((a, b) => a + b, 0);
  const concluded = new Set(
    leagues.filter((l) => l.concluded).map((l) => l.code)
  );

  const totalPredictions = scorecard.reduce((sum, r) => sum + r.n_predictions, 0);
  const totalGraded = scorecard.length > 0;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-4xl px-6 py-12">

        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
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
                      <td className="px-4 py-2 text-zinc-500">
                        {row.league}
                        {concluded.has(row.league) && <ConcludedBadge />}
                      </td>
                      <td className="px-4 py-2 text-black dark:text-zinc-50">
                        {marketLabel(row.market)}
                      </td>
                      <td className="px-4 py-2 text-right text-zinc-500">
                        {row.n_predictions}
                        {isSmallSample(row.n_predictions) && (
                          <SmallSampleBadge n={row.n_predictions} />
                        )}
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
                  how often it's actually right. Each market is broken into
                  confidence bands (e.g. predictions stated around 60% vs. around
                  80%) — the closer the stated and realized bars are within each
                  band, the more trustworthy the probabilities.
                </p>
                <div className="mt-4 space-y-6">
                  {Object.entries(
                    calibration.reduce<Record<string, CalibrationRow[]>>((acc, row) => {
                      const key = `${row.league}::${row.market}`;
                      (acc[key] ??= []).push(row);
                      return acc;
                    }, {})
                  ).map(([key, rows]) => {
                    const [league, market] = key.split("::");
                    const sorted = rows
                      .slice()
                      .sort((a, b) => a.avg_stated_prob - b.avg_stated_prob);
                    return (
                      <div key={key} className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                        <div className="text-sm font-medium text-black dark:text-zinc-50">
                          {marketLabel(market)}{" "}
                          <span className="font-normal text-zinc-500">({league})</span>
                          {concluded.has(league) && <ConcludedBadge />}
                        </div>
                        <div className="mt-3 space-y-3">
                          {sorted.map((row, i) => (
                            <div key={i}>
                              <div className="text-xs text-zinc-400">
                                Confidence band ~{(row.avg_stated_prob * 100).toFixed(0)}%
                                <span className="ml-1 text-zinc-500">(n={row.n})</span>
                                {isSmallSample(row.n) && <SmallSampleBadge n={row.n} />}
                              </div>
                              <div className="mt-1 space-y-1">
                                <div className="flex items-center gap-2">
                                  <span className="w-16 text-xs text-zinc-500">Stated</span>
                                  <div className="h-2 flex-1 rounded-full bg-zinc-100 dark:bg-zinc-800">
                                    <div className="h-2 rounded-full bg-zinc-400" style={{ width: `${row.avg_stated_prob * 100}%` }} />
                                  </div>
                                  <span className="w-12 text-right text-xs text-zinc-500">
                                    {(row.avg_stated_prob * 100).toFixed(0)}%
                                  </span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="w-16 text-xs text-zinc-500">Realized</span>
                                  <div className="h-2 flex-1 rounded-full bg-zinc-100 dark:bg-zinc-800">
                                    <div className="h-2 rounded-full bg-emerald-500" style={{ width: `${row.realized_rate * 100}%` }} />
                                  </div>
                                  <span className="w-12 text-right text-xs text-zinc-500">
                                    {(row.realized_rate * 100).toFixed(0)}%
                                  </span>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}

        {totalVoided > 0 && (
          <>
            <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
              Voided predictions
            </h2>
            <p className="mt-1 max-w-2xl text-sm text-zinc-500">
              {totalVoided.toLocaleString()} prediction
              {totalVoided === 1 ? " has" : "s have"} been voided and excluded
              from the rates above. A void is not a miss — it means the outcome
              could not be determined, most often because a named player never
              took the field. Voiding happens automatically by fixed rule, never
              by hand, and the reason is recorded against each one. They are
              listed here rather than quietly dropped.
            </p>
            <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                  <tr>
                    <th className="px-4 py-2 font-medium">Reason</th>
                    <th className="px-4 py-2 font-medium text-right">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(voidsByReason)
                    .sort((a, b) => b[1] - a[1])
                    .map(([reason, n]) => (
                      <tr key={reason} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                        <td className="px-4 py-2 text-black dark:text-zinc-50">
                          {VOID_REASON_LABELS[reason] || reason}
                        </td>
                        <td className="px-4 py-2 text-right text-zinc-500">{n}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
