"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { marketLabel } from "@/lib/markets";
import CalibrationSection from "./calibration-section";
import MarketComparisonSection from "./market-comparison-section";
import HomeAdvantageSection from "./home-advantage-section";
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
  sport: string;
}

interface CalibrationRow {
  league: string;
  market: string;
  side: string;
  avg_stated_prob: number;
  realized_rate: number;
  n: number;
  sport: string;
}

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

interface HomeAdvantageRow {
  league: string;
  season: string;
  gamma: number;
  n_matches: number;
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values)).sort();
}

function FilterSelect({
  label,
  allLabel,
  value,
  options,
  onChange,
  optionLabel = (o: string) => o,
}: {
  label: string;
  allLabel: string;
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
        <option value="">{allLabel}</option>
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
  marketComparison,
  homeAdvantage,
}: {
  scorecard: ScorecardRow[];
  calibration: CalibrationRow[];
  marketComparison: MarketComparisonRow[];
  homeAdvantage: HomeAdvantageRow[];
}) {
  const t = useTranslations("TrackRecordContent");
  const tSport = useTranslations("Sport");
  const searchParams = useSearchParams();
  const [sport, setSport] = useState(() => searchParams.get("sport") ?? "");
  const [league, setLeague] = useState(() => searchParams.get("league") ?? "");
  const [season, setSeason] = useState(() => searchParams.get("season") ?? "");
  const [market, setMarket] = useState(() => searchParams.get("market") ?? "");

  // Sync filters into the URL (?sport=&league=&season=&market=) so a
  // filtered view is shareable/bookmarkable -- this is what ADR-011's
  // "link to the relevant filtered Track Record view" needs to actually
  // resolve to something. Uses the native History API directly rather
  // than next/navigation's router: router.replace() would re-run this
  // page's server component and refetch scorecard/calibration for a
  // filter change that's already fully handled client-side.
  useEffect(() => {
    const params = new URLSearchParams();
    if (sport) params.set("sport", sport);
    if (league) params.set("league", league);
    if (season) params.set("season", season);
    if (market) params.set("market", market);
    const query = params.toString();
    const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [sport, league, season, market]);

  const sports = useMemo(() => uniqueSorted(scorecard.map((r) => r.sport)), [scorecard]);
  // League options narrow to the selected sport, so the dropdown never
  // offers a sport/league combo that can't match anything (e.g. NFL
  // while sport=soccer is selected).
  const leagues = useMemo(
    () => uniqueSorted(scorecard.filter((r) => !sport || r.sport === sport).map((r) => r.league)),
    [scorecard, sport]
  );
  const seasons = useMemo(() => uniqueSorted(scorecard.map((r) => r.season)), [scorecard]);
  const markets = useMemo(() => uniqueSorted(scorecard.map((r) => r.market)), [scorecard]);

  const filteredScorecard = scorecard.filter(
    (r) =>
      (!sport || r.sport === sport) &&
      (!league || r.league === league) &&
      (!season || r.season === season) &&
      (!market || r.market === market)
  );
  // Calibration rows have no season dimension -- the season filter only
  // narrows the "By market" table below, not the calibration cards.
  const filteredCalibration = calibration.filter(
    (r) => (!sport || r.sport === sport) && (!league || r.league === league) && (!market || r.market === market)
  );
  // Only 1X2 rows exist here -- the market filter would zero this
  // section out for every other market, so it only respects league.
  const filteredMarketComparison = marketComparison.filter(
    (r) => !league || r.league === league
  );
  const filteredHomeAdvantage = homeAdvantage.filter(
    (r) => !league || r.league === league
  );

  const totalPredictions = filteredScorecard.reduce((sum, r) => sum + r.n_predictions, 0);

  // Cross-sport calibration comparison -- deliberately computed from the
  // full, unfiltered `calibration` prop rather than filteredCalibration:
  // this is a standing "how does each sport calibrate" summary, not
  // something that should go empty because of an unrelated league/market
  // filter. Weighted by n so a sport with more graded bands doesn't get
  // drowned out by one with a handful of noisy small-sample bands.
  const calibrationBySport = useMemo(() => {
    const acc: Record<string, { errSum: number; n: number }> = {};
    for (const r of calibration) {
      const entry = (acc[r.sport] ??= { errSum: 0, n: 0 });
      entry.errSum += Math.abs(r.avg_stated_prob - r.realized_rate) * r.n;
      entry.n += r.n;
    }
    return Object.entries(acc)
      .map(([sport, { errSum, n }]) => ({ sport, n, meanAbsError: n > 0 ? errSum / n : 0 }))
      .sort((a, b) => a.meanAbsError - b.meanAbsError);
  }, [calibration]);

  return (
    <>
      <div className="mt-8 flex flex-wrap items-end justify-between gap-4">
        <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <span className="text-sm text-zinc-500">{t("totalGradedPredictions")}</span>
          <div className="text-2xl font-semibold text-black dark:text-zinc-50">
            {totalPredictions.toLocaleString("en-US")}
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <FilterSelect
            label={t("sport")}
            allLabel={t("all")}
            value={sport}
            options={sports}
            onChange={(v) => {
              setSport(v);
              // Reset league on sport change -- otherwise a league from
              // the old sport stays selected but no longer appears in
              // the (now sport-narrowed) League dropdown.
              setLeague("");
            }}
            optionLabel={tSport}
          />
          <FilterSelect label={t("league")} allLabel={t("all")} value={league} options={leagues} onChange={setLeague} />
          <FilterSelect label={t("season")} allLabel={t("all")} value={season} options={seasons} onChange={setSeason} />
          <FilterSelect
            label={t("market")}
            allLabel={t("all")}
            value={market}
            options={markets}
            onChange={setMarket}
            optionLabel={marketLabel}
          />
        </div>
      </div>

      {calibrationBySport.length > 1 && (
        <>
          <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
            {t("calibrationBySport")}
          </h2>
          <p className="mt-2 max-w-xl text-sm text-zinc-500">
            {t("calibrationBySportExplainer")}
          </p>
          <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">{t("sport")}</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">{t("gradedPredictions")}</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">{t("meanAbsGap")}</th>
                </tr>
              </thead>
              <tbody>
                {calibrationBySport.map((row) => (
                  <tr key={row.sport} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                    <td className="px-4 py-2 text-black dark:text-zinc-50">{tSport(row.sport)}</td>
                    <td className="px-4 py-2 text-right text-zinc-500">{row.n.toLocaleString("en-US")}</td>
                    <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                      {(row.meanAbsError * 100).toFixed(1)} pp
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">{t("byMarket")}</h2>
      {filteredScorecard.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-500">{t("noGradedPredictionsMatch")}</p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">{t("sport")}</th>
                <th scope="col" className="px-4 py-2 font-medium">{t("league")}</th>
                <th scope="col" className="px-4 py-2 font-medium">{t("season")}</th>
                <th scope="col" className="px-4 py-2 font-medium">{t("market")}</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">N</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("stated")}</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("realized")}</th>
              </tr>
            </thead>
            <tbody>
              {filteredScorecard.map((row, i) => (
                <tr key={i} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                  <td className="px-4 py-2 text-zinc-500">{tSport(row.sport)}</td>
                  <td className="px-4 py-2 text-zinc-500">{row.league}</td>
                  <td className="px-4 py-2 text-zinc-500">{row.season}</td>
                  <td className="px-4 py-2 text-black dark:text-zinc-50">{marketLabel(row.market)}</td>
                  <td className="px-4 py-2 text-right text-zinc-500">
                    {row.n_predictions}
                    {row.n_predictions < 5 && (
                      <span title={t("smallSampleWarning")} className="ml-1 text-amber-700 dark:text-amber-400">
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
        <span className="text-amber-700 dark:text-amber-400">&#9888;</span> {t("smallSampleFootnote")}
      </p>

      {filteredCalibration.length > 0 && (
        <>
          <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">{t("calibration")}</h2>
          <CalibrationSection calibration={filteredCalibration} />
        </>
      )}

      <MarketComparisonSection comparison={filteredMarketComparison} />

      <HomeAdvantageSection history={filteredHomeAdvantage} />

      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">{t("predictionLog")}</h2>
      <PredictionLog league={league} season={season} market={market} />
    </>
  );
}
