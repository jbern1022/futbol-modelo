import Link from "next/link";
import { marketLabel } from "@/lib/markets";

// See web/app/page.tsx's identical comment -- without this, Next.js
// statically prerenders this page at docker-host build time, which has
// no network route to the cluster-internal API_URL, baking a dead
// empty-data page into the deployed image.
export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Bet {
  prediction_id: number;
  match_id: number;
  kickoff_utc: string;
  market: string;
  side: string;
  model_probability: number;
  decimal_odds: number;
  stake: number;
  outcome: string;
  profit: number;
  bankroll_after: number;
}

async function getBankroll(): Promise<{ bets: Bet[]; starting_bankroll: number }> {
  try {
    // Same 1-hour edge cache as every other Track Record-style fetch on
    // this site -- the API itself already caches this for 5 minutes.
    const res = await fetch(`${API_URL}/v1/bankroll`, { next: { revalidate: 3600 } });
    if (!res.ok) return { bets: [], starting_bankroll: 0 };
    const data = await res.json();
    return { bets: data.bets || [], starting_bankroll: data.starting_bankroll ?? 0 };
  } catch {
    return { bets: [], starting_bankroll: 0 };
  }
}

const MARKET_COLORS: Record<string, string> = {
  "1X2": "#8b5cf6",
  BTTS: "#3b82f6",
  PLAYER_GOALS: "#10b981",
};

function BankrollChart({ bets, startingBankroll }: { bets: Bet[]; startingBankroll: number }) {
  if (bets.length === 0) return null;

  const markets = Array.from(new Set(bets.map((b) => b.market))).sort();
  const byMarket = markets.map((market) => ({
    market,
    bets: bets.filter((b) => b.market === market),
  }));

  const allBankrolls = [startingBankroll, ...bets.map((b) => b.bankroll_after)];
  const yMin = Math.min(...allBankrolls);
  const yMax = Math.max(...allBankrolls);
  // Pad the range so the curve doesn't touch the plot edges -- a flat
  // curve (yMin === yMax, e.g. a single bet or no variance yet) would
  // otherwise divide by zero in toY.
  const pad = Math.max((yMax - yMin) * 0.1, 5);
  const rangeMin = yMin - pad;
  const rangeMax = yMax + pad;

  const maxLen = Math.max(...byMarket.map((m) => m.bets.length));
  const plotW = Math.max(280, Math.min(maxLen * 12, 640));
  const plotH = 220;
  const padding = 48;
  const width = plotW + padding * 2;
  const height = plotH + padding * 2;

  const toY = (v: number) => padding + (1 - (v - rangeMin) / (rangeMax - rangeMin)) * plotH;
  const toX = (i: number, n: number) => padding + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);

  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto" style={{ minWidth: Math.min(width, 640) }} role="img" aria-label="Bankroll over time by market">
        <line x1={padding} y1={toY(startingBankroll)} x2={padding + plotW} y2={toY(startingBankroll)} stroke="currentColor" strokeOpacity={0.15} strokeDasharray="4 4" />
        <text x={padding + plotW + 4} y={toY(startingBankroll) + 4} fontSize={10} fill="currentColor" opacity={0.5}>
          start
        </text>
        {byMarket.map(({ market, bets: marketBets }) => {
          const color = MARKET_COLORS[market] ?? "#71717a";
          const points = [
            `${toX(0, marketBets.length + 1)},${toY(startingBankroll)}`,
            ...marketBets.map((b, i) => `${toX(i + 1, marketBets.length + 1)},${toY(b.bankroll_after)}`),
          ].join(" ");
          return (
            <g key={market}>
              <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeOpacity={0.85} />
            </g>
          );
        })}
      </svg>
      <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1">
        {markets.map((m) => (
          <div key={m} className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: MARKET_COLORS[m] ?? "#71717a" }} />
            {marketLabel(m)}
          </div>
        ))}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <span className="text-sm text-zinc-500">{label}</span>
      <div className="text-2xl font-semibold text-black dark:text-zinc-50">{value}</div>
    </div>
  );
}

export default async function BankrollPage() {
  const { bets, starting_bankroll: startingBankroll } = await getBankroll();

  const markets = Array.from(new Set(bets.map((b) => b.market))).sort();
  const totalStake = bets.reduce((sum, b) => sum + b.stake, 0);
  const totalProfit = bets.reduce((sum, b) => sum + b.profit, 0);
  const roiPct = totalStake > 0 ? (totalProfit / totalStake) * 100 : 0;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-3xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Paper-Trading Bankroll
        </h1>
        <p className="mt-4 max-w-2xl text-zinc-600 dark:text-zinc-400">
          A flat ${bets[0]?.stake?.toFixed(0) ?? "10"} stake on every graded prediction that had a
          real bookmaker price available before kickoff, priced at the earliest snapshot (the
          opening line, not closing). No compounding, no Kelly sizing &mdash; this is the honest
          baseline before anything fancier. Predictions with no odds available are skipped
          entirely, never given a fabricated price.
        </p>

        {bets.length === 0 ? (
          <div className="mt-10 rounded-lg border border-zinc-200 bg-white p-6 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            No bets recorded yet &mdash; this fills in as more predictions get graded with odds
            available before kickoff.
          </div>
        ) : (
          <>
            <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Bets placed" value={bets.length.toLocaleString("en-US")} />
              <StatCard label="Total staked" value={`$${totalStake.toFixed(0)}`} />
              <StatCard
                label="Net profit"
                value={`${totalProfit >= 0 ? "+" : ""}$${totalProfit.toFixed(2)}`}
              />
              <StatCard label="ROI" value={`${roiPct >= 0 ? "+" : ""}${roiPct.toFixed(1)}%`} />
            </div>

            <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
              Bankroll over time
            </h2>
            <BankrollChart bets={bets} startingBankroll={startingBankroll} />

            {bets.length < 30 && (
              <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                &#9888; Small sample ({bets.length} bets) &mdash; odds ingestion only started
                recently, so this curve will get more meaningful as more graded predictions
                accumulate real bookmaker prices.
              </p>
            )}

            <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
              By market
            </h2>
            <div className="mt-4 space-y-1 text-sm">
              {markets.map((m) => {
                const marketBets = bets.filter((b) => b.market === m);
                const marketProfit = marketBets.reduce((sum, b) => sum + b.profit, 0);
                return (
                  <div key={m} className="flex justify-between border-b border-zinc-100 py-2 dark:border-zinc-800">
                    <span className="text-zinc-500">{marketLabel(m)}</span>
                    <span className="text-black dark:text-zinc-50">
                      {marketBets.length} bets &middot;{" "}
                      {marketProfit >= 0 ? "+" : ""}
                      {marketProfit.toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
