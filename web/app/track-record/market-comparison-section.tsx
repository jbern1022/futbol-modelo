"use client";

import { LocalDate } from "../local-date";

interface MarketComparisonRow {
  league: string;
  match_id: number;
  home_team: string;
  away_team: string;
  kickoff_utc: string;
  status: string;
  side: string;
  model_probability: number;
  market_probability: number;
  n_bookmakers: number;
}

const SIDE_LABELS: Record<string, string> = { home: "Home win", away: "Away win", draw: "Draw" };

export default function MarketComparisonSection({
  comparison,
}: {
  comparison: MarketComparisonRow[];
}) {
  if (comparison.length === 0) return null;

  const rows = [...comparison].sort(
    (a, b) => new Date(a.kickoff_utc).getTime() - new Date(b.kickoff_utc).getTime()
  );

  return (
    <>
      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
        Model vs. the market
      </h2>
      <p className="mt-2 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
        The model&apos;s stated probability next to real bookmaker odds (vig removed,
        averaged across bookmakers) for match-result predictions on fixtures that
        haven&apos;t been graded yet.
      </p>
      <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">Fixture</th>
              <th scope="col" className="px-4 py-2 font-medium">Outcome</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Model</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Market</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Diff</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Books</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const diff = row.model_probability - row.market_probability;
              const diffColor =
                Math.abs(diff) < 0.05
                  ? "text-zinc-500"
                  : diff > 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-600 dark:text-rose-400";
              return (
                <tr
                  key={`${row.match_id}-${row.side}`}
                  className="border-b border-zinc-100 last:border-0 dark:border-zinc-800"
                >
                  <td className="px-4 py-2 text-black dark:text-zinc-50">
                    {row.home_team} vs {row.away_team}
                    <div className="text-xs text-zinc-400">
                      {row.league} &middot;{" "}
                      <LocalDate date={row.kickoff_utc} options={{ month: "short", day: "numeric" }} />
                    </div>
                  </td>
                  <td className="px-4 py-2 text-zinc-500">
                    {SIDE_LABELS[row.side] ?? row.side}
                  </td>
                  <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                    {(row.model_probability * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                    {(row.market_probability * 100).toFixed(1)}%
                  </td>
                  <td className={`px-4 py-2 text-right font-medium ${diffColor}`}>
                    {diff > 0 ? "+" : ""}
                    {(diff * 100).toFixed(1)}
                  </td>
                  <td className="px-4 py-2 text-right text-zinc-500">{row.n_bookmakers}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-zinc-400">
        Diff is the model&apos;s probability minus the market&apos;s. Positive means the
        model is more confident than the market; it isn&apos;t yet known which one is
        right until the match is graded.
      </p>
    </>
  );
}
