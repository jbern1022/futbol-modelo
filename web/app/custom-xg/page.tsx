import Link from "next/link";

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

const FEATURE_IMPORTANCE: FeatureImportance[] = [
  { feature: "angle_rad", label: "Angle to goal", importance: 2389 },
  { feature: "distance_m", label: "Distance to goal", importance: 2232 },
  { feature: "body_part", label: "Body part", importance: 499 },
  { feature: "situation", label: "Situation (open play / corner / etc.)", importance: 495 },
  { feature: "is_penalty", label: "Is penalty", importance: 85 },
];

export default function CustomXgPage() {
  const logLossDiffPct = ((UNDERSTAT_LOG_LOSS - OUR_LOG_LOSS) / UNDERSTAT_LOG_LOSS) * 100;

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Custom xG Model vs. Understat
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          Expected goals (xG) estimates how likely a shot was to result in a
          goal, based on where it was taken from and how. This project
          already ingests Understat&apos;s own xG as a benchmark alongside
          every shot&apos;s raw coordinates &mdash; so the natural next
          question is whether a model trained on that same data can match
          or beat it.
        </p>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          Short answer: <strong className="text-black dark:text-zinc-50">no, not yet</strong>.
          This page is the honest result, not a flattering one &mdash; in the
          same spirit as the{" "}
          <a href="/lessons-learned" className="underline hover:no-underline">
            Lessons Learned
          </a>{" "}
          page: a site with no visible struggles is less credible than one
          that shows its actual results.
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">Method</h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          A LightGBM classifier trained on distance-to-goal and angle-to-goal
          (standard shot-geometry derivations from each shot&apos;s
          normalized pitch coordinates, not the raw x/y directly), the
          shot&apos;s situation (open play, corner, set piece, direct
          free kick), body part, and an explicit penalty flag. Trained on
          four complete seasons (2021-22 through 2024-25) across EPL, Serie
          A, and La Liga &mdash; the only leagues with shot-level data
          ingested (Understat doesn&apos;t cover MLS) &mdash; and evaluated
          on a held-out fifth season (2025-26) it never trained on, the
          same walk-forward discipline used throughout this project.
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">Result</h2>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium"></th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Log loss</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Brier score</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-zinc-100 dark:border-zinc-800">
                <td className="px-4 py-2 text-black dark:text-zinc-50">Our model</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{OUR_LOG_LOSS.toFixed(4)}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{OUR_BRIER.toFixed(4)}</td>
              </tr>
              <tr>
                <td className="px-4 py-2 text-black dark:text-zinc-50">Understat&apos;s xG</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{UNDERSTAT_LOG_LOSS.toFixed(4)}</td>
                <td className="px-4 py-2 text-right text-black dark:text-zinc-50">{UNDERSTAT_BRIER.toFixed(4)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          {N_SHOTS.toLocaleString("en-US")} held-out shots, {N_GOALS.toLocaleString("en-US")} goals.
          Lower is better on both metrics. Our model&apos;s log loss is{" "}
          {Math.abs(logLossDiffPct).toFixed(1)}% worse than Understat&apos;s.
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          Why it falls short
        </h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          The gap isn&apos;t a bug. Understat encodes penalties as a fixed
          spot with a hardcoded benchmark xG (0.7613 &mdash; the known
          historical penalty conversion rate, not a per-shot prediction) --
          worth checking directly, since it could have made the comparison
          unfair in Understat&apos;s favor. It didn&apos;t: adding an
          explicit penalty flag to this model changed the result by
          nothing, because distance and angle alone already put every
          penalty at the same point on the pitch, and the model had already
          learned that pattern from geometry. The real gap is that
          Understat almost certainly has access to information this
          public dataset doesn&apos;t carry &mdash; defender and goalkeeper
          positions at the moment of the shot, most likely &mdash; and no
          amount of feature engineering on coordinates and shot type alone
          closes that.
        </p>

        <h2 className="mt-10 text-lg font-semibold text-black dark:text-zinc-50">
          Calibration
        </h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Despite losing on log loss and Brier score, the model is still
          well-calibrated &mdash; grouped by predicted probability decile,
          the realized goal rate tracks the stated one closely at every
          level. It&apos;s a worse discriminator than Understat&apos;s
          model (worse at separating likely goals from unlikely ones), not
          a dishonest one.
        </p>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium text-right">Stated</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Realized</th>
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
          Feature importance
        </h2>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">Feature</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Relative importance</th>
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
          What&apos;s next
        </h2>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Two real, separate pieces of follow-up work, not attempted here:
          closing the feature gap would need richer shot-context data than
          any public source currently provides to this project, and
          extending this model to MLS &mdash; the whole reason to build a
          custom xG model instead of depending on Understat in the first
          place &mdash; needs a new MLS shot-event ingestion pipeline,
          since Understat doesn&apos;t cover MLS and nothing else currently
          supplies shot coordinates for it.
        </p>

        <a href="/how-it-works" className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
          How it works &rarr;
        </a>
      </main>
    </div>
  );
}
