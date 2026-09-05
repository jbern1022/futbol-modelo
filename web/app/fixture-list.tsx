"use client";

import { useState } from "react";
import { LocalDate } from "./local-date";

interface Fixture {
  match_id: number;
  league: string;
  season: string;
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

function fixtureSummary(f: Fixture): string {
  if (f.headline_statement && f.headline_probability !== null) {
    return `${f.headline_statement}, ${(f.headline_probability * 100).toFixed(0)}%`;
  }
  return `${f.n_predictions} prediction${f.n_predictions === 1 ? "" : "s"}`;
}

const LEAGUE_COLORS: Record<string, string> = {
  MLS: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  EPL: "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300",
  SERIE_A: "bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300",
  LA_LIGA: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
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
  const leagues = Array.from(new Set(fixtures.map((f) => f.league))).sort();
  const [selected, setSelected] = useState<string | null>(null);

  const visible = selected ? fixtures.filter((f) => f.league === selected) : fixtures;

  return (
    <div>
      {leagues.length > 1 && (
        <div role="group" aria-label="Filter fixtures by league" className="mt-6 flex flex-wrap gap-2">
          <button
            onClick={() => setSelected(null)}
            aria-pressed={selected === null}
            className={`rounded-md px-3 py-1 text-xs font-medium uppercase tracking-wide ${
              selected === null
                ? "bg-black text-white dark:bg-zinc-50 dark:text-black"
                : "border border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-400"
            }`}
          >
            All
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
        <div className="mt-10 text-zinc-500">No upcoming fixtures for {selected}.</div>
      ) : (
        <div className="mt-6 space-y-3">
          {visible.map((f) => (
            <a
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
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
