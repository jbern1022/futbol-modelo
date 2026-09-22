import Link from "next/link";

// See web/app/page.tsx's identical comment -- without this, Next.js
// statically prerenders this page at docker-host build time, which has
// no network route to the cluster-internal API_URL, baking a dead
// empty-data page into the deployed image.
export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Rating {
  league: string;
  team: string;
  atk: number;
  atk_ci_low: number;
  atk_ci_high: number;
  dfn: number;
  dfn_ci_low: number;
  dfn_ci_high: number;
  n_boot_samples: number;
  n_matches: number;
  computed_at: string;
}

async function getTeamRatings(): Promise<Rating[]> {
  try {
    // Same 1-hour edge cache as every other Track Record-style fetch
    // on this site -- the API itself already caches this for 5 minutes.
    const res = await fetch(`${API_URL}/v1/team-ratings`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.ratings || [];
  } catch {
    return [];
  }
}

const LEAGUE_LABELS: Record<string, string> = {
  EPL: "Premier League",
  SERIE_A: "Serie A",
  LA_LIGA: "La Liga",
  MLS: "MLS",
};

// Attack: higher is better (more expected goals). Defence: LOWER is
// better in Dixon-Coles' own parameterization (it's a log-rate added
// to the OPPONENT's expected goals) -- flipped here only for display
// so "further right = stronger" reads the same way on both charts,
// with the true sign kept in a tooltip for anyone checking the math.
function RatingChart({
  ratings,
  field,
  ciLowField,
  ciHighField,
  flip,
  label,
}: {
  ratings: Rating[];
  field: "atk" | "dfn";
  ciLowField: "atk_ci_low" | "dfn_ci_low";
  ciHighField: "atk_ci_high" | "dfn_ci_high";
  flip: boolean;
  label: string;
}) {
  const sign = flip ? -1 : 1;
  const los = ratings.map((r) => sign * (flip ? r[ciHighField] : r[ciLowField]));
  const his = ratings.map((r) => sign * (flip ? r[ciLowField] : r[ciHighField]));
  const allVals = [...los, ...his];
  const vMin = Math.min(...allVals);
  const vMax = Math.max(...allVals);
  const pad = Math.max((vMax - vMin) * 0.1, 0.05);
  const rangeMin = vMin - pad;
  const rangeMax = vMax + pad;

  const rowH = 22;
  const chartW = 420;
  const leftLabelW = 130;
  const padding = 12;
  const height = ratings.length * rowH + padding * 2;
  const width = leftLabelW + chartW + padding * 2;

  const toX = (v: number) => leftLabelW + ((v - rangeMin) / (rangeMax - rangeMin)) * chartW;
  const zeroX = toX(0);

  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto" style={{ minWidth: Math.min(width, 640) }} role="img" aria-label={`${label} ratings with 90% confidence intervals`}>
        <line x1={zeroX} y1={0} x2={zeroX} y2={height} stroke="currentColor" strokeOpacity={0.15} strokeDasharray="3 3" />
        {ratings.map((r, i) => {
          const y = padding + i * rowH + rowH / 2;
          const v = sign * r[field];
          const lo = toX(sign * (flip ? r[ciHighField] : r[ciLowField]));
          const hi = toX(sign * (flip ? r[ciLowField] : r[ciHighField]));
          const x = toX(v);
          return (
            <g key={r.team}>
              <text x={leftLabelW - 8} y={y + 4} fontSize={10} textAnchor="end" fill="currentColor" opacity={0.7}>
                {r.team.length > 16 ? r.team.slice(0, 15) + "…" : r.team}
              </text>
              <line x1={lo} y1={y} x2={hi} y2={y} stroke="#8b5cf6" strokeWidth={2} strokeOpacity={0.5} />
              <line x1={lo} y1={y - 3} x2={lo} y2={y + 3} stroke="#8b5cf6" strokeOpacity={0.5} />
              <line x1={hi} y1={y - 3} x2={hi} y2={y + 3} stroke="#8b5cf6" strokeOpacity={0.5} />
              <circle cx={x} cy={y} r={3} fill="#8b5cf6">
                <title>{`${r.team}: ${label} ${r[field].toFixed(3)} (90% CI ${r[ciLowField].toFixed(3)} to ${r[ciHighField].toFixed(3)}, n=${r.n_boot_samples} bootstrap samples)`}</title>
              </circle>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default async function TeamRatingsPage() {
  const ratings = await getTeamRatings();
  const leagues = Array.from(new Set(ratings.map((r) => r.league))).sort();

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-3xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Team Ratings
        </h1>
        <p className="mt-4 max-w-2xl text-zinc-600 dark:text-zinc-400">
          Dixon-Coles fits an attack and defence rating for every team from all
          available match history, weighted toward recent form. Error bars are a
          90% bootstrap confidence interval (200 refits on resampled data) &mdash;
          a wide bar means the model genuinely isn&apos;t sure yet, usually from a
          team with too few matches to pin down. Sorted by attack rating, highest
          first. Both charts read the same way: further right is stronger.
        </p>

        {ratings.length === 0 ? (
          <div className="mt-10 rounded-lg border border-zinc-200 bg-white p-6 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            No ratings computed yet &mdash; run scripts/compute_team_ratings.py, or check
            back once it has.
          </div>
        ) : (
          leagues.map((league) => {
            const leagueRatings = ratings
              .filter((r) => r.league === league)
              .sort((a, b) => b.atk - a.atk);
            return (
              <section key={league} className="mt-10">
                <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
                  {LEAGUE_LABELS[league] ?? league}
                </h2>
                <p className="mt-1 text-xs text-zinc-400">
                  {leagueRatings.length} teams &middot; fit on {leagueRatings[0]?.n_matches ?? 0}{" "}
                  matches
                </p>

                <h3 className="mt-4 text-sm font-medium text-zinc-600 dark:text-zinc-400">
                  Attack
                </h3>
                <RatingChart
                  ratings={leagueRatings}
                  field="atk"
                  ciLowField="atk_ci_low"
                  ciHighField="atk_ci_high"
                  flip={false}
                  label="Attack"
                />

                <h3 className="mt-4 text-sm font-medium text-zinc-600 dark:text-zinc-400">
                  Defence
                </h3>
                <p className="text-xs text-zinc-400">
                  Shown flipped so further right still means stronger &mdash; Dixon-Coles&apos;
                  raw defence parameter is lower for a better defence.
                </p>
                <RatingChart
                  ratings={leagueRatings}
                  field="dfn"
                  ciLowField="dfn_ci_low"
                  ciHighField="dfn_ci_high"
                  flip={true}
                  label="Defence"
                />
              </section>
            );
          })
        )}
      </main>
    </div>
  );
}
