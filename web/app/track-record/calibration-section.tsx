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

// One fixed color per market rather than a generated palette -- there
// are only 7 markets total, so a lookup reads clearer than a hash.
const MARKET_COLORS: Record<string, string> = {
  "1X2": "#f59e0b",
  BTTS: "#8b5cf6",
  TOTAL_GOALS: "#3b82f6",
  CORNERS: "#10b981",
  SOT: "#ec4899",
  PLAYER_GOALS: "#ef4444",
  PLAYER_SAVES: "#06b6d4",
};

// A table of "records" says a model is tracked; a curve hugging the
// diagonal says "calibrated" at a glance. Plots every row across every
// market/league/side at once -- the detailed bars below are still
// there for anyone who wants the per-band breakdown.
function ReliabilityDiagram({ calibration }: { calibration: CalibrationRow[] }) {
  const pad = 44;
  const plot = 360;
  const size = plot + pad * 2;
  const toX = (p: number) => pad + p * plot;
  const toY = (p: number) => pad + (1 - p) * plot;

  const markets = Array.from(new Set(calibration.map((r) => r.market)));

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-md mx-auto" role="img" aria-label="Reliability diagram: stated probability vs. realized rate">
        {/* gridlines + axis labels every 25% */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={toX(t)} y1={pad} x2={toX(t)} y2={pad + plot} stroke="currentColor" strokeOpacity={0.08} />
            <line x1={pad} y1={toY(t)} x2={pad + plot} y2={toY(t)} stroke="currentColor" strokeOpacity={0.08} />
            <text x={toX(t)} y={pad + plot + 18} fontSize={11} textAnchor="middle" fill="currentColor" opacity={0.5}>
              {(t * 100).toFixed(0)}%
            </text>
            <text x={pad - 10} y={toY(t) + 4} fontSize={11} textAnchor="end" fill="currentColor" opacity={0.5}>
              {(t * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        {/* perfect-calibration diagonal */}
        <line x1={toX(0)} y1={toY(0)} x2={toX(1)} y2={toY(1)} stroke="currentColor" strokeOpacity={0.3} strokeDasharray="4 4" />
        {/* axis titles */}
        <text x={pad + plot / 2} y={size - 6} fontSize={12} textAnchor="middle" fill="currentColor" opacity={0.6}>
          Stated probability
        </text>
        <text x={12} y={pad + plot / 2} fontSize={12} textAnchor="middle" fill="currentColor" opacity={0.6} transform={`rotate(-90, 12, ${pad + plot / 2})`}>
          Realized rate
        </text>
        {/* one point per calibration row */}
        {calibration.map((row, i) => (
          <circle
            key={i}
            cx={toX(row.avg_stated_prob)}
            cy={toY(row.realized_rate)}
            r={3 + Math.min(Math.sqrt(row.n), 6)}
            fill={MARKET_COLORS[row.market] ?? "#71717a"}
            fillOpacity={opacityForN(row.n) * 0.75}
          />
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1">
        {markets.map((m) => (
          <div key={m} className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKET_COLORS[m] ?? "#71717a" }} />
            {marketLabel(m)}
          </div>
        ))}
      </div>
      <p className="mt-2 text-center text-xs text-zinc-400">
        Points on the dashed line are perfectly calibrated. Dot size scales with sample size.
      </p>
    </div>
  );
}

export default function CalibrationSection({ calibration }: { calibration: CalibrationRow[] }) {
  const [bandOnly, setBandOnly] = useState(false);

  const filteredCalibration = bandOnly
    ? calibration.filter((r) => r.avg_stated_prob >= TARGET_BAND[0] && r.avg_stated_prob <= TARGET_BAND[1])
    : calibration;

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

      {filteredCalibration.length > 0 && (
        <div className="mt-4">
          <ReliabilityDiagram calibration={filteredCalibration} />
        </div>
      )}

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
