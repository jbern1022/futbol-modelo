import Link from "next/link";

interface SeasonResult {
  season: string;
  n: number;
  rps: number;
  log_loss: number;
  accuracy: number;
}

// Real walk-forward backtest output, scripts/train_dixon_coles.py
// (weekly refits through each holdout season, scored against matches
// that were still in the future at fit time -- the same discipline the
// live pipeline uses, not an in-sample fit). Static data, not a live
// query: these are prior, closed seasons that don't change, and this
// avoids a server-rendered page depending on cluster-internal DB access
// at build time (see footer.tsx's comment on the same class of issue).
// Regenerate by re-running the script per season if more history lands.
const RESULTS: Record<string, SeasonResult[]> = {
  EPL: [
    { season: "2022-23", n: 380, rps: 0.1998, log_loss: 0.971, accuracy: 0.5474 },
    { season: "2023-24", n: 378, rps: 0.1943, log_loss: 0.9459, accuracy: 0.582 },
    { season: "2024-25", n: 380, rps: 0.2011, log_loss: 0.9812, accuracy: 0.5289 },
    { season: "2025-26", n: 380, rps: 0.2084, log_loss: 1.0251, accuracy: 0.4632 },
  ],
  SERIE_A: [
    { season: "2022-23", n: 380, rps: 0.2027, log_loss: 1.0019, accuracy: 0.5132 },
    { season: "2023-24", n: 380, rps: 0.1985, log_loss: 1.008, accuracy: 0.4868 },
    { season: "2024-25", n: 380, rps: 0.1948, log_loss: 0.9886, accuracy: 0.5132 },
    { season: "2025-26", n: 379, rps: 0.1993, log_loss: 0.9866, accuracy: 0.5145 },
  ],
};

const LEAGUE_LABELS: Record<string, string> = { EPL: "EPL", SERIE_A: "Serie A" };

function ResultsTable({ league, rows }: { league: string; rows: SeasonResult[] }) {
  const rpsValues = rows.map((r) => r.rps);
  const min = Math.min(...rpsValues);
  const max = Math.max(...rpsValues);
  return (
    <div className="mt-4">
      <h3 className="text-base font-semibold text-black dark:text-zinc-50">
        {LEAGUE_LABELS[league] ?? league}
      </h3>
      <div className="mt-2 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">Season</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Matches</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">RPS</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Log loss</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">1X2 accuracy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.season} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                <td className="px-4 py-2 text-black dark:text-zinc-50">{r.season}</td>
                <td className="px-4 py-2 text-right text-zinc-500">{r.n}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                  {r.rps.toFixed(4)}
                </td>
                <td className="px-4 py-2 text-right text-zinc-500">{r.log_loss.toFixed(4)}</td>
                <td className="px-4 py-2 text-right text-zinc-500">
                  {(r.accuracy * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1.5 text-xs text-zinc-500">
        RPS range across these {rows.length} seasons: {min.toFixed(4)}&ndash;{max.toFixed(4)}.
      </p>
    </div>
  );
}

export default function BacktestPage() {
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Season-over-Season Backtest
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          A model can look good on one lucky season and fall apart on the
          next. To check for that, the 1X2 match model (Dixon-Coles) is
          walk-forward backtested against every complete season with prior
          history: refit weekly through the season, always scored against
          matches that were still in the future relative to the fit &mdash;
          the same discipline the live pipeline uses, not an in-sample fit
          that would flatter the numbers.
        </p>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          Scored two ways: <strong className="text-black dark:text-zinc-50">ranked
          probability score</strong> (RPS, lower is better &mdash; rewards a
          calibrated full distribution over win/draw/loss, not just picking
          the right winner) and <strong className="text-black dark:text-zinc-50">log
          loss</strong> (lower is better, penalizes confident wrong calls
          harder than uncertain ones). A credible RPS for this kind of model
          on a top-flight league sits roughly in the 0.19&ndash;0.21 range;
          random guessing lands well above 0.22.
        </p>

        <div className="mt-10 space-y-10">
          {Object.entries(RESULTS).map(([league, rows]) => (
            <ResultsTable key={league} league={league} rows={rows} />
          ))}
        </div>

        <p className="mt-10 text-zinc-600 dark:text-zinc-400">
          Every season for both leagues lands inside that credible band, with
          no single outlier season propping up the average. That&apos;s the
          actual claim this page exists to support: the model&apos;s
          performance isn&apos;t a story about one good year.
        </p>

        <a href="/track-record" className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
          See the live track record &rarr;
        </a>
      </main>
    </div>
  );
}
