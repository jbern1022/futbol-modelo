"use client";

import { useState } from "react";
import { marketLabel } from "@/lib/markets";

interface CalibrationRow {
  league: string;
  market: string;
  side: string;
  avg_stated_prob: number;
  realized_rate: number;
  n: number;
}

// "over"/"under" read fine bare; a bare "home"/"away"/"draw" doesn't say
// what it's the side of, so 1X2 sides get spelled out per-market.
function sideLabel(market: string, side: string): string {
  if (market === "1X2") {
    return { home: "Home win", away: "Away win", draw: "Draw" }[side] ?? side;
  }
  return side.charAt(0).toUpperCase() + side.slice(1);
}

// Matches TARGET_BAND in src/predictions/generator.py -- the confidence
// range the slate generator actually selects for, and the range the
// project's whole calibration claim rests on.
const TARGET_BAND: [number, number] = [0.6, 0.75];

// Simple tiered opacity rather than a continuous formula, matching the
// n<5 threshold already used elsewhere on this page (ADR-007).
function opacityForN(n: number): number {
  if (n < 5) return 0.45;
  if (n < 15) return 0.75;
  return 1;
}

export default function CalibrationSection({ calibration }: { calibration: CalibrationRow[] }) {
  const [bandOnly, setBandOnly] = useState(false);

  const grouped = Object.entries(
    calibration.reduce<Record<string, CalibrationRow[]>>((acc, row) => {
      const key = `${row.league}::${row.market}::${row.side}`;
      (acc[key] ??= []).push(row);
      return acc;
    }, {})
  ).map(([key, rows]) => {
    const [league, market, side] = key.split("::");
    const sorted = rows.slice().sort((a, b) => a.avg_stated_prob - b.avg_stated_prob);
    const filtered = bandOnly
      ? sorted.filter((r) => r.avg_stated_prob >= TARGET_BAND[0] && r.avg_stated_prob <= TARGET_BAND[1])
      : sorted;
    return { key, league, market, side, rows: filtered };
  }).filter((g) => g.rows.length > 0);

  return (
    <>
      <div className="mt-4 flex items-center justify-between">
        <p className="max-w-xl text-sm text-zinc-500">
          A well-calibrated model&apos;s stated confidence should roughly match
          how often it&apos;s actually right. Each market is broken into
          confidence bands (e.g. predictions stated around 60% vs. around
          80%) — the closer the stated and realized bars are within each
          band, the more trustworthy the probabilities. Bars for smaller
          samples are shown lighter.
        </p>
        <button
          onClick={() => setBandOnly((v) => !v)}
          className={`ml-4 whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium ${
            bandOnly
              ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
              : "border border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
          }`}
        >
          {bandOnly ? "Showing 60–75% band only" : "Isolate 60–75% band"}
        </button>
      </div>

      {grouped.length === 0 ? (
        <p className="mt-6 text-sm text-zinc-500">No bands in the 60–75% range yet.</p>
      ) : (
        <div className="mt-4 space-y-6">
          {grouped.map(({ key, league, market, side, rows }) => (
            <div key={key} className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <div className="text-sm font-medium text-black dark:text-zinc-50">
                {marketLabel(market)} &mdash; {sideLabel(market, side)}{" "}
                <span className="font-normal text-zinc-500">({league})</span>
              </div>
              <div className="mt-3 space-y-3">
                {rows.map((row, i) => (
                  <div key={i} style={{ opacity: opacityForN(row.n) }}>
                    <div className="text-xs text-zinc-400">
                      Confidence band ~{(row.avg_stated_prob * 100).toFixed(0)}%
                      <span className="ml-1 text-zinc-500">(n={row.n})</span>
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
          ))}
        </div>
      )}
    </>
  );
}
