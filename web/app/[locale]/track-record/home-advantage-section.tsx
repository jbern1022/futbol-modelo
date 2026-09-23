import { useTranslations } from "next-intl";

interface HomeAdvantageRow {
  league: string;
  season: string;
  gamma: number;
  n_matches: number;
}

// One fixed color per league, matching the palette style already used
// for markets in calibration-section.tsx (small fixed set, a lookup
// reads clearer than a generated palette).
const LEAGUE_COLORS: Record<string, string> = {
  EPL: "#8b5cf6",
  SERIE_A: "#3b82f6",
  LA_LIGA: "#ef4444",
  MLS: "#10b981",
  WC: "#f59e0b",
};

// gamma (Dixon-Coles' home-advantage term) lives in log-goal-rate space,
// not a bounded 0-1 probability -- fit values across every league/season
// backfilled so far land well inside this range, but it's not a hard
// mathematical bound, just the honest observed range. Widening this if a
// future season fits outside it is expected, not a bug.
const Y_MIN = 0;
const Y_MAX = 0.5;

export default function HomeAdvantageSection({ history }: { history: HomeAdvantageRow[] }) {
  const t = useTranslations("HomeAdvantageSection");
  if (history.length === 0) return null;

  const leagues = Array.from(new Set(history.map((r) => r.league))).sort();
  const byLeague = leagues.map((league) => ({
    league,
    rows: history
      .filter((r) => r.league === league)
      // Seasons are league-specific labels ("2021-22" vs "2021" vs a
      // single World Cup year) -- string sort is the honest ordering
      // available without hardcoding a season-format parser per league.
      .sort((a, b) => a.season.localeCompare(b.season)),
  }));
  const maxSeasons = Math.max(...byLeague.map((l) => l.rows.length));

  const pad = 44;
  const plotW = Math.max(280, (maxSeasons - 1) * 70);
  const plotH = 240;
  const width = plotW + pad * 2;
  const height = plotH + pad * 2;
  const toY = (g: number) => pad + (1 - (g - Y_MIN) / (Y_MAX - Y_MIN)) * plotH;
  const toX = (i: number) => pad + (maxSeasons <= 1 ? plotW / 2 : (i / (maxSeasons - 1)) * plotW);

  return (
    <>
      <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
        {t("heading")}
      </h2>
      <p className="mt-2 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
        {t("explainer")}
      </p>
      <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto" style={{ minWidth: Math.min(width, 640) }} role="img" aria-label="Home advantage (gamma) by league and season">
          {[0, 0.125, 0.25, 0.375, 0.5].map((gridline) => (
            <g key={gridline}>
              <line x1={pad} y1={toY(gridline)} x2={pad + plotW} y2={toY(gridline)} stroke="currentColor" strokeOpacity={0.08} />
              <text x={pad - 10} y={toY(gridline) + 4} fontSize={11} textAnchor="end" fill="currentColor" opacity={0.5}>
                {gridline.toFixed(3)}
              </text>
            </g>
          ))}
          {byLeague.map(({ league, rows }) => {
            const color = LEAGUE_COLORS[league] ?? "#71717a";
            const points = rows.map((r, i) => `${toX(i)},${toY(r.gamma)}`).join(" ");
            return (
              <g key={league}>
                <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeOpacity={0.85} />
                {rows.map((r, i) => (
                  <g key={r.season}>
                    <circle cx={toX(i)} cy={toY(r.gamma)} r={4} fill={color}>
                      <title>{`${league} ${r.season}: gamma ${r.gamma.toFixed(4)} (n=${r.n_matches})`}</title>
                    </circle>
                    {league === byLeague[0].league && (
                      <text x={toX(i)} y={pad + plotH + 18} fontSize={10} textAnchor="middle" fill="currentColor" opacity={0.5}>
                        {r.season}
                      </text>
                    )}
                  </g>
                ))}
              </g>
            );
          })}
        </svg>
        <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1">
          {leagues.map((l) => (
            <div key={l} className="flex items-center gap-1.5 text-xs text-zinc-500">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: LEAGUE_COLORS[l] ?? "#71717a" }} />
              {l}
            </div>
          ))}
        </div>
        <p className="mt-2 text-center text-xs text-zinc-400">
          {t("axisExplainer")}
        </p>
      </div>
    </>
  );
}
