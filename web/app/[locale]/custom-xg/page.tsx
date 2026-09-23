import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";

interface DecileRow {
  stated: number;
  realized: number;
  n: number;
}

interface FeatureImportance {
  feature: string;
  label: string;
  importance: number;
}

// Real output of scripts/train_xg_model.py, run 2026-09-14 against the
// live database (106,949 shots, EPL/SERIE_A/LA_LIGA -- the only leagues
// with shot-level data; Understat doesn't cover MLS). Trained on
// 2021-22..2024-25, held out 2025-26 -- never shuffled across time.
// Static data, not a live query, for the same reason /backtest and the
// footer's freshness indicator are: a server-rendered page can't depend
// on cluster-internal DB access at docker-host build time. Re-run the
// script to refresh if more seasons land.
const N_SHOTS = 28846;
const N_GOALS = 3326;
const OUR_LOG_LOSS = 0.28;
const UNDERSTAT_LOG_LOSS = 0.2619;
const OUR_BRIER = 0.0791;
const UNDERSTAT_BRIER = 0.0742;

const CALIBRATION: DecileRow[] = [
  { stated: 0.015, realized: 0.027, n: 2885 },
  { stated: 0.025, realized: 0.026, n: 2894 },
  { stated: 0.033, realized: 0.037, n: 2877 },
  { stated: 0.043, realized: 0.043, n: 2952 },
  { stated: 0.052, realized: 0.049, n: 2839 },
  { stated: 0.072, realized: 0.07, n: 2862 },
  { stated: 0.101, realized: 0.095, n: 2898 },
  { stated: 0.14, realized: 0.13, n: 2870 },
  { stated: 0.197, realized: 0.189, n: 2885 },
  { stated: 0.522, realized: 0.489, n: 2884 },
];

export default function CustomXgPage() {
  const t = useTranslations("CustomXgPage");
  const FEATURE_IMPORTANCE: FeatureImportance[] = [
    { feature: "angle_rad", label: t("featureAngle"), importance: 2389 },
    { feature: "distance_m", label: t("featureDistance"), importance: 2232 },
    { feature: "body_part", label: t("featureBodyPart"), importance: 499 },
    { feature: "situation", label: t("featureSituation"), importance: 495 },
    { feature: "is_penalty", label: t("featureIsPenalty"), importance: 85 },
  ];
  const logLossDiffPct = ((UNDERSTAT_LOG_LOSS - OUR_LOG_LOSS) / UNDERSTAT_LOG_LOSS) * 100;
  const strong = (chunks: React.ReactNode) => (
    <strong className="text-black dark:text-zinc-50">{chunks}</strong>
  );
  const lessonsLearnedLink = (chunks: React.ReactNode) => (
    <Link href="/lessons-learned" className="underline hover:no-underline">{chunks}</Link>
  );
  const mlsGapLink = (chunks: React.ReactNode) => (
    <Link href="/lessons-learned#mls-xg-data-gap" className="underline hover:no-underline">{chunks}</Link>
  );

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; {t("backToFixtures")}
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          {t("heading")}
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          {t("intro")}
        </p>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          {t.rich("shortAnswer", { strong, lessonsLearnedLink })}
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">{t("method")}</h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {t("methodBody")}
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">{t("result")}</h2>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium"></th>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("logLoss")}</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("brierScore")}</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-zinc-100 dark:border-zinc-800">
                <td className="px-4 py-2 text-black dark:text-zinc-50">{t("ourModel")}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{OUR_LOG_LOSS.toFixed(4)}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{OUR_BRIER.toFixed(4)}</td>
              </tr>
              <tr>
                <td className="px-4 py-2 text-black dark:text-zinc-50">{t("understatXg")}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{UNDERSTAT_LOG_LOSS.toFixed(4)}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{UNDERSTAT_BRIER.toFixed(4)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          {t("resultFootnote", {
            shots: N_SHOTS.toLocaleString("en-US"),
            goals: N_GOALS.toLocaleString("en-US"),
            pct: Math.abs(logLossDiffPct).toFixed(1),
          })}
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          {t("whyItFallsShort")}
        </h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {t("whyItFallsShortBody")}
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          {t("calibration")}
        </h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {t("calibrationBody")}
        </p>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("stated")}</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("realized")}</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">n</th>
              </tr>
            </thead>
            <tbody>
              {CALIBRATION.map((row, i) => (
                <tr key={i} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                  <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                    {(row.stated * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2 text-right text-black dark:text-zinc-50">
                    {(row.realized * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-2 text-right text-zinc-500">{row.n.toLocaleString("en-US")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          {t("featureImportance")}
        </h2>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">{t("feature")}</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">{t("relativeImportance")}</th>
              </tr>
            </thead>
            <tbody>
              {FEATURE_IMPORTANCE.map((row) => (
                <tr key={row.feature} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
                  <td className="px-4 py-2 text-black dark:text-zinc-50">{row.label}</td>
                  <td className="px-4 py-2 text-right text-zinc-500">{row.importance.toLocaleString("en-US")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          {t("whatsNext")}
        </h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {t("whatsNextBody1")}
        </p>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          {t.rich("whatsNextBody2", { mlsGapLink })}
        </p>

        <Link href="/how-it-works" className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
          {t("howItWorks")} &rarr;
        </Link>
      </main>
    </div>
  );
}
