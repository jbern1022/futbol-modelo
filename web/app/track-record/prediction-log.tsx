"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { marketLabel } from "@/lib/markets";
import { leagueBadge, cleanStatement, outcomeBadge } from "@/lib/prediction-display";

interface LogRow {
  prediction_id: number;
  market: string;
  statement: string;
  side: string | null;
  probability: number;
  outcome: string;
  actual_value: number | null;
  subject_team: string | null;
  subject_player: string | null;
  match_id: number;
  league: string;
  season: string;
  home: string;
  away: string;
  kickoff_utc: string;
}

const PAGE_SIZE = 25;

// The honest, unfiltered record this page's own copy promises -- every
// individual graded prediction, not just aggregates. Respects the same
// league/season/market filters as the tables above it, via its own
// fetch (not scorecard/calibration's server-fetched props) since the
// full set could be thousands of rows -- too much to ship to the
// client just to filter locally.
export default function PredictionLog({
  league,
  season,
  market,
}: {
  league: string;
  season: string;
  market: string;
}) {
  const [outcome, setOutcome] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<LogRow[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);

  // Any filter change (including the parent's league/season/market)
  // resets to page one -- staying on offset=200 after switching leagues
  // would silently show an empty or wrong page.
  useEffect(() => {
    setOffset(0);
  }, [league, season, market, outcome]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (league) params.set("league", league);
    if (season) params.set("season", season);
    if (market) params.set("market", market);
    if (outcome) params.set("outcome", outcome);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));

    let cancelled = false;
    setLoading(true);
    fetch(`/api/predictions?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        setRows(data.predictions || []);
        setCount(data.count || 0);
      })
      .catch(() => {
        if (!cancelled) {
          setRows([]);
          setCount(0);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [league, season, market, outcome, offset]);

  const from = count === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, count);

  return (
    <>
      <div className="mt-4 flex items-center justify-between gap-4">
        <p className="max-w-xl text-sm text-zinc-500">
          Every individually graded prediction — statement, stated probability,
          outcome, and what actually happened. Most recent first.
        </p>
        <label className="flex items-center gap-1.5 text-xs text-zinc-500">
          Outcome
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-black dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50"
          >
            <option value="">All</option>
            <option value="hit">Hits</option>
            <option value="miss">Misses</option>
          </select>
        </label>
      </div>

      {count === 0 && !loading ? (
        <p className="mt-4 text-sm text-zinc-500">No graded predictions match these filters.</p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th className="px-4 py-2 font-medium">Prediction</th>
                <th className="px-4 py-2 font-medium">Fixture</th>
                <th className="px-4 py-2 font-medium text-right">Stated</th>
                <th className="px-4 py-2 font-medium text-right">Actual</th>
              </tr>
            </thead>
            <tbody className={loading ? "opacity-50" : ""}>
              {rows.map((row) => (
                <tr key={row.prediction_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                  <td className="px-4 py-2">
                    <Link href={`/prediction/${row.prediction_id}`} className="text-black hover:underline dark:text-zinc-50">
                      {cleanStatement(row)}
                    </Link>
                    {outcomeBadge(row.outcome)}
                    <div className="mt-0.5 flex items-center gap-1.5 text-xs text-zinc-400">
                      {leagueBadge(row.league)}
                      {marketLabel(row.market)}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-zinc-500">
                    <Link href={`/fixtures/${row.match_id}`} className="hover:underline">
                      {row.home} vs {row.away}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                    {(row.probability * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2 text-right text-zinc-500">
                    {row.actual_value !== null ? row.actual_value : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {count > 0 && (
        <div className="mt-3 flex items-center justify-between text-xs text-zinc-500">
          <span>
            {from}&ndash;{to} of {count}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              disabled={offset === 0}
              className="rounded-md border border-zinc-200 px-3 py-1 font-medium text-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-800 dark:text-zinc-300"
            >
              Previous
            </button>
            <button
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= count}
              className="rounded-md border border-zinc-200 px-3 py-1 font-medium text-zinc-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-800 dark:text-zinc-300"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </>
  );
}
