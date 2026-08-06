"use client";

import { useState, useEffect, useRef } from "react";

const LEAGUES = ["MLS", "EPL", "SERIE_A", "LA_LIGA", "WC"];
const MARKETS = [
  { value: "1X2", label: "Match Result" },
  { value: "BTTS", label: "Both Teams to Score" },
  { value: "TOTAL_GOALS", label: "Total Goals" },
  { value: "CORNERS", label: "Corners" },
  { value: "SOT", label: "Shots on Target" },
  { value: "PLAYER_GOALS", label: "Anytime Goalscorer" },
  { value: "PLAYER_SAVES", label: "Goalkeeper Saves" },
];
const TEAM_STATS = [
  { value: "corners", label: "Corners" },
  { value: "shots_on_target", label: "Shots on Target" },
  { value: "shots", label: "Shots" },
  { value: "fouls", label: "Fouls" },
  { value: "yellows", label: "Yellow Cards" },
];

interface ScorecardRow {
  league: string;
  market: string;
  n_predictions: number;
}

interface AskResponse {
  answer: string;
  n_predictions?: number;
  n_games?: number;
  hit_rate?: number;
  average?: number;
  avg_confidence?: number;
  small_sample: boolean;
  disclaimer?: string;
}

export interface PeteyWidgetProps {
  initialTeam?: string;
  initialLeague?: string;
  initialMode?: "accuracy" | "form";
  compact?: boolean;
}

export default function PeteyWidget({
  initialTeam = "",
  initialLeague = "MLS",
  initialMode,
  compact = false,
}: PeteyWidgetProps) {
  const resolvedInitialMode: "accuracy" | "form" =
    initialMode || (initialTeam ? "form" : "accuracy");

  const [mode, setMode] = useState<"accuracy" | "form">(resolvedInitialMode);

  const [league, setLeague] = useState("MLS");
  const [market, setMarket] = useState("CORNERS");

  const [teams, setTeams] = useState<string[]>([]);
  const [formLeague, setFormLeague] = useState(initialLeague);
  const [team, setTeam] = useState(initialTeam);
  const [stat, setStat] = useState("corners");
  const [games, setGames] = useState(10);

  const [response, setResponse] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isFirstTeamsFetch = useRef(true);

  // (league, market) pairs that actually have graded predictions -- avoids
  // offering combinations that always answer "no data yet" (e.g. player
  // props outside MLS). Falls back to showing every option if this fetch
  // fails, rather than hiding the whole form.
  const [availablePairs, setAvailablePairs] = useState<Set<string> | null>(null);

  useEffect(() => {
    fetch("/api/scorecard")
      .then((r) => r.json())
      .then((d) => {
        const rows: ScorecardRow[] = d.scorecard || [];
        const pairs = new Set(
          rows.filter((r) => r.n_predictions > 0).map((r) => `${r.league}:${r.market}`)
        );
        setAvailablePairs(pairs);
      })
      .catch(() => setAvailablePairs(null));
  }, []);

  const availableMarkets = availablePairs
    ? MARKETS.filter((m) => availablePairs.has(`${league}:${m.value}`))
    : MARKETS;
  // Derived rather than synced via effect: if the previously-picked market
  // isn't offered for this league, fall back to the first available one
  // without an extra render round-trip.
  const effectiveMarket = availableMarkets.some((m) => m.value === market)
    ? market
    : (availableMarkets[0]?.value ?? market);

  useEffect(() => {
    fetch(`/api/teams?league=${formLeague}`)
      .then((r) => r.json())
      .then((d) => setTeams(d.teams || []))
      .catch(() => setTeams([]));
    if (isFirstTeamsFetch.current) {
      isFirstTeamsFetch.current = false;
    } else {
      setTeam("");
    }
  }, [formLeague]);

  async function handleAsk() {
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const url = mode === "accuracy" ? "/api/ask" : "/api/ask/team-form";
      const body = mode === "accuracy"
        ? { market: effectiveMarket, league }
        : { team, stat, games };
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Petey couldn't process that.");
      const data: AskResponse = await res.json();
      setResponse(data);
    } catch {
      setError("Couldn't reach Petey right now — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  const canAsk =
    (mode === "accuracy" && availableMarkets.length > 0) ||
    (mode === "form" && team.trim().length > 0);
  const datalistId = compact ? "petey-teams-compact" : "petey-teams";

  return (
    <div>
      <div className="flex gap-2">
        <button onClick={() => { setMode("accuracy"); setResponse(null); }} className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === "accuracy" ? "bg-black text-white dark:bg-zinc-50 dark:text-black" : "border border-zinc-200 text-zinc-700 dark:border-zinc-800 dark:text-zinc-300"}`}>
          Prediction Accuracy
        </button>
        <button onClick={() => { setMode("form"); setResponse(null); }} className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === "form" ? "bg-black text-white dark:bg-zinc-50 dark:text-black" : "border border-zinc-200 text-zinc-700 dark:border-zinc-800 dark:text-zinc-300"}`}>
          Team Recent Form
        </button>
      </div>

      {mode === "accuracy" && (
        <div className={`mt-4 flex flex-wrap items-end gap-3`}>
          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
              League
            </label>
            <select value={league} onChange={(e) => setLeague(e.target.value)} className="mt-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50">
              {LEAGUES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Market
            </label>
            <select value={effectiveMarket} onChange={(e) => setMarket(e.target.value)} className="mt-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50">
              {availableMarkets.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
            {availablePairs && availableMarkets.length === 0 && (
              <p className="mt-1 text-xs text-zinc-500">No graded predictions yet for {league}.</p>
            )}
          </div>
        </div>
      )}

      {mode === "form" && (
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
              League
            </label>
            <select value={formLeague} onChange={(e) => setFormLeague(e.target.value)} className="mt-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50">
              {LEAGUES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Team
            </label>
            <input list={datalistId} value={team} onChange={(e) => setTeam(e.target.value)} placeholder="Start typing a team..." className={`mt-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50 ${compact ? "w-full" : "w-56"}`} />
            <datalist id={datalistId}>
              {teams.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Stat
            </label>
            <select value={stat} onChange={(e) => setStat(e.target.value)} className="mt-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-50">
              {TEAM_STATS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Last {games} games
            </label>
            <input
              type="range"
              min={1}
              max={20}
              value={games}
              onChange={(e) => setGames(Number(e.target.value))}
              className="mt-3 w-40 accent-black dark:accent-zinc-50"
            />
          </div>
        </div>
      )}

      <button onClick={handleAsk} disabled={loading || !canAsk} className="mt-4 rounded-md bg-black px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-50 dark:text-black dark:hover:bg-zinc-200">
        {loading ? "Asking Petey..." : "Ask Petey"}
      </button>

      {error && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {error}
        </div>
      )}

      {response && (
        <div className="mt-6 rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <p className="text-black dark:text-zinc-50">{response.answer}</p>

          {(response.n_predictions ?? 0) > 0 && (
            <p className="mt-3 text-sm text-zinc-500">
              n={response.n_predictions}
              {response.hit_rate !== undefined && (
                <> &middot; {(response.hit_rate * 100).toFixed(1)}% hit rate</>
              )}
              {" "}&middot;{" "}
              <a href="/track-record" className="underline hover:no-underline">
                see full breakdown
              </a>
            </p>
          )}

          {response.disclaimer && (
            <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
              &#9888; {response.disclaimer}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
