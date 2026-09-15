"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

interface StandingsRow {
  team: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_diff: number;
  points: number;
}

interface StandingsData {
  league: string;
  season: string;
  available_seasons: string[];
  standings: StandingsRow[];
}

// World Cup deliberately excluded -- it's group stage + knockout, not a
// round-robin, and this schema has no stage/group column to separate
// them. A fabricated points table would count knockout draws (several
// real ones in the data, later decided on penalties) as league-style
// draws worth a point, mixing group-stage and knockout results into one
// table that doesn't correspond to anything that actually happened.
// Real leagues only, where "standings" means what it normally means.
const LEAGUES = ["EPL", "SERIE_A", "LA_LIGA", "MLS"];

export default function StandingsPage() {
  const searchParams = useSearchParams();
  const [league, setLeague] = useState(() => {
    const fromUrl = searchParams.get("league");
    return fromUrl && LEAGUES.includes(fromUrl) ? fromUrl : "MLS";
  });
  const [season, setSeason] = useState(() => searchParams.get("season") ?? "");
  const [data, setData] = useState<StandingsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams({ league });
    if (season) params.set("season", season);
    const url = `/standings?${params.toString()}`;
    window.history.replaceState(null, "", url);

    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetch(`/api/standings?${params.toString()}`)
      .then((res) => res.json())
      .then((d) => {
        if (cancelled) return;
        setData(d);
        // The API resolves an unset season to its own default -- pick
        // that up so the season dropdown reflects what's actually shown
        // instead of staying stuck on "All seasons".
        if (!season && d.season) setSeason(d.season);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [league, season]);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">
            Standings
          </h1>
          <div className="flex flex-wrap gap-3">
            <label className="flex items-center gap-1.5 text-xs text-zinc-500">
              League
              <select
                value={league}
                onChange={(e) => {
                  setLeague(e.target.value);
                  setSeason(""); // let the new league resolve its own default season
                }}
                className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-black dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50"
              >
                {LEAGUES.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </label>
            {data && data.available_seasons.length > 1 && (
              <label className="flex items-center gap-1.5 text-xs text-zinc-500">
                Season
                <select
                  value={season}
                  onChange={(e) => setSeason(e.target.value)}
                  className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-black dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {data.available_seasons.slice().reverse().map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>

        {!data && !loading && (
          <div className="mt-10 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            Could not load standings.
          </div>
        )}

        {data && data.standings.length === 0 && (
          <p className="mt-10 text-zinc-500">No finished matches for {data.season} yet.</p>
        )}

        {data && data.standings.length > 0 && (
          <div className={`mt-6 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800 ${loading ? "opacity-50" : ""}`}>
            <table className="w-full text-left text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">#</th>
                  <th scope="col" className="px-3 py-2 font-medium">Team</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">P</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">W</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">D</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">L</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">GD</th>
                  <th scope="col" className="px-3 py-2 font-medium text-right">Pts</th>
                </tr>
              </thead>
              <tbody>
                {data.standings.map((row, i) => (
                  <tr key={row.team} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                    <td className="px-3 py-2 text-zinc-400">{i + 1}</td>
                    <td className="px-3 py-2">
                      <Link href={`/team/${encodeURIComponent(row.team)}`} className="text-black hover:underline dark:text-zinc-50">
                        {row.team}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-right text-zinc-500">{row.played}</td>
                    <td className="px-3 py-2 text-right text-zinc-500">{row.won}</td>
                    <td className="px-3 py-2 text-right text-zinc-500">{row.drawn}</td>
                    <td className="px-3 py-2 text-right text-zinc-500">{row.lost}</td>
                    <td className="px-3 py-2 text-right text-zinc-500">
                      {row.goal_diff > 0 ? "+" : ""}{row.goal_diff}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold text-black dark:text-zinc-50">
                      {row.points}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
