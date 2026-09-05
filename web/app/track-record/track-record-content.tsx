"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { marketLabel } from "@/lib/markets";
import CalibrationSection from "./calibration-section";
import PredictionLog from "./prediction-log";

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
  side: string;
  avg_stated_prob: number;
  realized_rate: number;
  n: number;
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values)).sort();
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  optionLabel = (o: string) => o,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  optionLabel?: (o: string) => string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-zinc-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-black dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {optionLabel(o)}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function TrackRecordContent({
  scorecard,
  calibration,
}: {
  scorecard: ScorecardRow[];
  calibration: CalibrationRow[];
}) {
  const searchParams = useSearchParams();
  const [league, setLeague] = useState(() => searchParams.get("league") ?? "");
  const [season, setSeason] = useState(() => searchParams.get("season") ?? "");
  const [market, setMarket] = useState(() => searchParams.get("market") ?? "");

  // Sync filters into the URL (?league=&season=&market=) so a filtered
  // view is shareable/bookmarkable -- this is what ADR-011's "link to
  // the relevant filtered Track Record view" needs to actually resolve
  // to something. Uses the native History API directly rather than
  // next/navigation's router: router.replace() would re-run this page's
  // server component and refetch scorecard/calibration for a filter
  // change that's already fully handled client-side.
  useEffect(() => {
    const params = new URLSearchParams();
    if (league) params.set("league", league);
    if (season) params.set("season", season);
    if (market) params.set("market", market);
    const query = params.toString();
    const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [league, season, market]);

  const leagues = useMemo(() => uniqueSorted(scorecard.map((r) => r.league)), [scorecard]);
  const seasons = useMemo(() => uniqueSorted(scorecard.map((r) => r.season)), [scorecard]);
  const markets = useMemo(() => uniqueSorted(scorecard.map((r) => r.market)), [scorecard]);

  const filteredScorecard = scorecard.filter(
    (r) =>
      (!league || r.league === league) &&
      (!season || r.season === season) &&
      (!market || r.market === market)
  );
  // Calibration rows have no season dimension -- the season filter only
  // narrows the "By market" table below, not the calibration cards.
  const filteredCalibration = calibration.filter(
    (r) => (!league || r.league === league) && (!market || r.market === market)
  );

  const totalPredictions = filteredScorecard.reduce((sum, r) => sum + r.n_predictions, 0);

  return (
    <>
      <div className="mt-8 flex flex-wrap items-end justify-between gap-4">
        <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <span className="text-sm text-zinc-500">Total graded predictions</span>
          <div className="text-2xl font-semibold text-black dark:text-zinc-50">
            {totalPredictions.toLocaleString()}
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <FilterSelect label="League" value={league} options={leagues} onChange={setLeague} />
          <FilterSelect label="Season" value={season} options={seasons} onChange={setSeason} />
          <FilterSelect
            label="Market"
            value={market}
            options={markets}
            onChange={setMarket}
            optionLabel={marketLabel}
          />
        </div>
      </div>

      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">By market</h2>
      {filteredScorecard.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-500">No graded predictions match these filters.</p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th className="px-4 py-2 font-medium">League</th>
                <th className="px-4 py-2 font-medium">Season</th>
                <th className="px-4 py-2 font-medium">Market</th>
                <th className="px-4 py-2 font-medium text-right">N</th>
                <th className="px-4 py-2 font-medium text-right">Stated</th>
                <th className="px-4 py-2 font-medium text-right">Realized</th>
              </tr>
            </thead>
            <tbody>
              {filteredScorecard.map((row, i) => (
                <tr key={i} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                  <td className="px-4 py-2 text-zinc-500">{row.league}</td>
                  <td className="px-4 py-2 text-zinc-500">{row.season}</td>
                  <td className="px-4 py-2 text-black dark:text-zinc-50">{marketLabel(row.market)}</td>
                  <td className="px-4 py-2 text-right text-zinc-500">
                    {row.n_predictions}
                    {row.n_predictions < 5 && (
                      <span title="Small sample -- treat this cautiously" className="ml-1 text-amber-600 dark:text-amber-400">
                        &#9888;
                      </span>
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
      )}
      <p className="mt-2 text-xs text-zinc-400">
        <span className="text-amber-600 dark:text-amber-400">&#9888;</span> marks a market with
        fewer than 5 graded predictions -- treat those numbers cautiously.
      </p>

      {filteredCalibration.length > 0 && (
        <>
          <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">Calibration</h2>
          <CalibrationSection calibration={filteredCalibration} />
        </>
      )}

      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">Prediction log</h2>
      <PredictionLog league={league} season={season} market={market} />
    </>
  );
}
