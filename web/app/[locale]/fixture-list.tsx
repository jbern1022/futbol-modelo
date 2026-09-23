"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { LocalDate } from "./local-date";
import { Link } from "@/i18n/navigation";

interface Fixture {
  match_id: number;
  league: string;
  season: string;
  sport: string;
  home: string;
  away: string;
  kickoff_utc: string;
  status: string;
  home_score: number | null;
  away_score: number | null;
  n_predictions: number;
  headline_statement: string | null;
  headline_probability: number | null;
}

const LEAGUE_COLORS: Record<string, string> = {
  MLS: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  EPL: "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300",
  SERIE_A: "bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300",
  LA_LIGA: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  NFL: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  NBA: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  WC: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
};

function leagueBadge(league: string) {
  const style = LEAGUE_COLORS[league] || "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${style}`}>
      {league}
    </span>
  );
}

export default function FixtureList({ fixtures }: { fixtures: Fixture[] }) {
  const t = useTranslations("FixtureList");
  const tSport = useTranslations("Sport");

  function fixtureSummary(f: Fixture): string {
    if (f.headline_statement && f.headline_probability !== null) {
      return `${f.headline_statement}, ${(f.headline_probability * 100).toFixed(0)}%`;
    }
    return t("nPredictions", { n: f.n_predictions });
  }

  const sports = Array.from(new Set(fixtures.map((f) => f.sport))).sort();
  const [selectedSport, setSelectedSport] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  // League options narrow to the selected sport, same reasoning as
  // Track Record's Sport -> League narrowing: never offer a league
  // that can't match anything for the currently selected sport.
  const leagues = Array.from(
    new Set(fixtures.filter((f) => !selectedSport || f.sport === selectedSport).map((f) => f.league))
  ).sort();

  const visible = fixtures.filter(
    (f) => (!selectedSport || f.sport === selectedSport) && (!selected || f.league === selected)
  );

  return (
    <div>
      {sports.length > 1 && (
        <div role="group" aria-label={t("filterBySport")} className="mt-6 flex flex-wrap gap-2">
          <button
            onClick={() => {
              setSelectedSport(null);
              setSelected(null);
            }}
            aria-pressed={selectedSport === null}
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              selectedSport === null
                ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
                : "border border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
            }`}
          >
            {t("allSports")}
          </button>
          {sports.map((sp) => (
            <button
              key={sp}
              onClick={() => {
                setSelectedSport(sp);
                // Reset league on sport change -- otherwise a league
                // from the old sport stays selected but no longer
                // appears in the (now sport-narrowed) league row.
                setSelected(null);
              }}
              aria-pressed={selectedSport === sp}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                selectedSport === sp
                  ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
                  : "border border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
              }`}
            >
              {tSport(sp)}
            </button>
          ))}
        </div>
      )}

      {leagues.length > 1 && (
        <div role="group" aria-label={t("filterByLeague")} className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => setSelected(null)}
            aria-pressed={selected === null}
            className={`rounded-md px-3 py-1 text-xs font-medium uppercase tracking-wide ${
              selected === null
                ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
                : "border border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
            }`}
          >
            {t("all")}
          </button>
          {leagues.map((l) => (
            <button
              key={l}
              onClick={() => setSelected(l)}
              aria-pressed={selected === l}
              className={`rounded-md px-3 py-1 text-xs font-medium uppercase tracking-wide ${
                selected === l
                  ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
                  : "border border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
              }`}
            >
              {l}
            </button>
          ))}
        </div>
      )}

      {visible.length === 0 ? (
        <div className="mt-10 text-zinc-500">
          {t("noUpcomingFixturesFor", {
            filter: selected || (selectedSport && tSport(selectedSport)) || t("theseFilters"),
          })}
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {visible.map((f) => (
            <Link
              key={f.match_id}
              href={`/fixtures/${f.match_id}`}
              className="block rounded-lg border border-zinc-200 bg-white p-4 transition-colors hover:border-zinc-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700"
            >
              <div className="flex items-center justify-between">
                <div>
                  {leagueBadge(f.league)}
                  <div className="mt-1 text-lg font-medium text-black dark:text-zinc-50">
                    {f.home} vs {f.away}
                  </div>
                </div>
                <div className="text-right">
                  <LocalDate
                    date={f.kickoff_utc}
                    className="text-sm text-zinc-500"
                    options={{ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }}
                  />
                  <div className="mt-1 text-xs text-zinc-400">{fixtureSummary(f)}</div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
