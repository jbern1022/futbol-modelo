import { useTranslations } from "next-intl";

// In-play home/draw/away probability over the match (ADR-011, ADR-013).
// Deliberately separate from the locked pre-match predictions: it's
// recomputed from the live score about once a minute and never graded.

export interface LiveWinProbPoint {
  minute: number;
  home_score: number;
  away_score: number;
  home: number;
  draw: number;
  away: number;
}

export interface LiveEvent {
  minute: number;
  extra_minute: number | null;
  type: string;
  detail: string | null;
  side: "home" | "away";
  player: string | null;
}

export interface LiveWinProb {
  league: string;
  red_card_calibrated: boolean;
  series: LiveWinProbPoint[];
  events: LiveEvent[];
}

const COLORS = { home: "#2563eb", draw: "#71717a", away: "#d97706" } as const;
type Outcome = keyof typeof COLORS;

export default function LiveWinProbChart({ data, home, away }: { data: LiveWinProb; home: string; away: string }) {
  const t = useTranslations("FixturePage");
  const { series, events } = data;
  if (series.length === 0) return null;

  const plotW = 600;
  const plotH = 200;
  const padL = 40;
  const padR = 16;
  const padT = 20;
  const padB = 28;
  const width = plotW + padL + padR;
  const height = plotH + padT + padB;
  // status.elapsed parks at 90 through stoppage, so 90 is the right edge.
  const toX = (minute: number) => padL + (Math.min(Math.max(minute, 0), 90) / 90) * plotW;
  const toY = (p: number) => padT + (1 - p) * plotH;

  // Step line: a probability holds until the next tick, then jumps --
  // a straight diagonal would invent values between ticks.
  const stepPoints = (key: Outcome) => {
    const pts: string[] = [];
    series.forEach((pt, i) => {
      if (i > 0) pts.push(`${toX(pt.minute)},${toY(series[i - 1][key])}`);
      pts.push(`${toX(pt.minute)},${toY(pt[key])}`);
    });
    return pts.join(" ");
  };

  const last = series[series.length - 1];
  const labels: Record<Outcome, string> = { home, draw: t("draw"), away };
  const pct = (p: number) => `${Math.round(p * 100)}%`;
  const summary = t("liveWinProbSummary", {
    minute: last.minute,
    score: `${last.home_score}-${last.away_score}`,
    home: pct(last.home),
    draw: pct(last.draw),
    away: pct(last.away),
  });

  return (
    <section className="mt-10">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">
        {t("liveWinProbTitle")}
      </h2>
      <p className="mb-3 text-xs text-zinc-500">{t("liveWinProbNote")}</p>
      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <svg viewBox={`0 0 ${width} ${height}`} className="mx-auto w-full" style={{ minWidth: 320 }} role="img" aria-label={summary}>
          {[0, 0.5, 1].map((p) => (
            <g key={p}>
              <line x1={padL} x2={padL + plotW} y1={toY(p)} y2={toY(p)} stroke="currentColor" strokeOpacity={0.12} />
              <text x={padL - 6} y={toY(p) + 3} fontSize={10} textAnchor="end" fill="currentColor" opacity={0.5}>
                {pct(p)}
              </text>
            </g>
          ))}
          {[0, 45, 90].map((m) => (
            <text key={m} x={toX(m)} y={height - 8} fontSize={10} textAnchor="middle" fill="currentColor" opacity={0.5}>
              {m}&apos;
            </text>
          ))}
          {events.map((e, i) => {
            const x = toX(e.minute);
            const isGoal = e.type === "Goal";
            const when = e.extra_minute ? `${e.minute}+${e.extra_minute}'` : `${e.minute}'`;
            const who = e.player ? ` — ${e.player}` : "";
            const team = e.side === "home" ? home : away;
            return (
              <g key={i}>
                <title>{`${when} ${isGoal ? t("goal") : t("redCard")} (${team})${who}`}</title>
                <line x1={x} x2={x} y1={padT} y2={padT + plotH} stroke={isGoal ? COLORS[e.side] : "#dc2626"} strokeOpacity={0.5} strokeDasharray="3 3" />
                {isGoal ? (
                  <circle cx={x} cy={padT - 8} r={4} fill={COLORS[e.side]} />
                ) : (
                  <rect x={x - 3} y={padT - 13} width={6} height={9} fill="#dc2626" />
                )}
              </g>
            );
          })}
          {(Object.keys(COLORS) as Outcome[]).map((key) => (
            <polyline key={key} points={stepPoints(key)} fill="none" stroke={COLORS[key]} strokeWidth={2} strokeLinejoin="round" />
          ))}
        </svg>
        <div className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1">
          {(Object.keys(COLORS) as Outcome[]).map((key) => (
            <div key={key} className="flex items-center gap-1.5 text-xs text-zinc-500">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[key] }} />
              {labels[key]} {pct(last[key])}
            </div>
          ))}
        </div>
        <p className="mt-2 text-center text-xs text-zinc-500">{summary}</p>
        {!data.red_card_calibrated && (
          <p className="mt-1 text-center text-xs text-zinc-400">{t("redCardUncalibrated")}</p>
        )}
      </div>
    </section>
  );
}
