import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";

// See web/app/page.tsx's identical comment -- without this, Next.js
// statically prerenders this page at docker-host build time, which has
// no network route to the cluster-internal API_URL, baking a dead
// empty-data page into the deployed image.
export const dynamic = "force-dynamic";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ChangelogRow {
  model_name: string;
  version_tag: string;
  trained_at: string;
  training_window: string | null;
  params: Record<string, unknown>;
  train_metrics: Record<string, unknown>;
}

async function getChangelog(): Promise<ChangelogRow[]> {
  try {
    // The API itself already caches this for 5 minutes; an hour here
    // cuts requests reaching the API pod at all, not just its DB load
    // -- same pattern as every other Track Record fetch on this site.
    const res = await fetch(`${API_URL}/v1/model-changelog`, { next: { revalidate: 3600 } });
    if (!res.ok) return [];
    const data = await res.json();
    return data.changelog || [];
  } catch {
    return [];
  }
}

const LEAGUE_LABELS: Record<string, string> = {
  epl: "EPL",
  mls: "MLS",
  serie_a: "Serie A",
  la_liga: "La Liga",
  nba: "NBA",
  nfl: "NFL",
};

function modelLabel(name: string, slateGeneratorSuffix: string): string {
  if (name.startsWith("slate_generator_")) {
    const key = name.slice("slate_generator_".length);
    return `${LEAGUE_LABELS[key] ?? key} ${slateGeneratorSuffix}`;
  }
  return name;
}

// train_metrics/params shapes differ per model (see api/main.py's
// model_changelog endpoint docstring) -- this is a real object, not a
// fixed schema, so render it as key: value pairs rather than assuming
// specific fields exist. Numbers get a few decimal places; everything
// else is stringified plainly.
function formatValue(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(4);
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function MetricsList({ metrics }: { metrics: Record<string, unknown> }) {
  const entries = Object.entries(metrics);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-zinc-500">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-1">
          <dt className="font-medium">{k}:</dt>
          <dd>{formatValue(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default async function ModelChangelogPage() {
  const t = await getTranslations("ModelChangelogPage");
  const changelog = await getChangelog();

  const modelNames = Array.from(new Set(changelog.map((r) => r.model_name))).sort();
  const byModel = modelNames.map((name) => ({
    name,
    rows: changelog.filter((r) => r.model_name === name),
  }));

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-3xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; {t("backToFixtures")}
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          {t("heading")}
        </h1>
        <p className="mt-4 max-w-2xl text-zinc-600 dark:text-zinc-400">
          {t("explainer")}
        </p>

        {changelog.length === 0 && (
          <div className="mt-10 rounded-lg border border-zinc-200 bg-white p-6 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            {t("noRetrainHistory")}
          </div>
        )}

        <div className="mt-10 space-y-10">
          {byModel.map(({ name, rows }) => (
            <section key={name}>
              <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
                {modelLabel(name, t("slateGenerator"))}
              </h2>
              <p className="mt-1 text-xs text-zinc-400">
                {t("retrainsRecorded", { n: rows.length })}
              </p>
              <div className="mt-3 space-y-3">
                {rows.map((r, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-mono text-xs text-zinc-500">
                        {new Date(r.trained_at).toLocaleString("en-US", {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })}
                      </span>
                      <span className="text-xs text-zinc-400">{t("version", { tag: r.version_tag })}</span>
                    </div>
                    {r.training_window && (
                      <p className="mt-1 text-xs text-zinc-500">
                        {t("trainedOn", { window: r.training_window })}
                      </p>
                    )}
                    <MetricsList metrics={r.train_metrics} />
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
