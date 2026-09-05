import Link from "next/link";

export default function HowItWorksPage() {
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          How Futbol Modelo Works
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          This isn&apos;t a static demo — it&apos;s a real, running system.
        </p>

        <p className="mt-6 text-zinc-600 dark:text-zinc-400">
          Every morning, an automated pipeline:
        </p>

        <ol className="mt-4 space-y-4 text-zinc-700 dark:text-zinc-300">
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">1.</span>
            <span>
              <strong className="text-black dark:text-zinc-50">Pulls fresh match data</strong>{" "}
              across four leagues (MLS, Premier League, Serie A, La Liga).
            </span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">2.</span>
            <span>
              <strong className="text-black dark:text-zinc-50">Generates predictions</strong>{" "}
              using two model families — a Dixon-Coles statistical model for match
              outcomes, and gradient-boosted models (LightGBM) for player and team
              props (corners, shots on target, goalscorers, saves). Every model had
              to prove it beats a naive baseline before being allowed to ship.
            </span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">3.</span>
            <span>
              <strong className="text-black dark:text-zinc-50">Locks each prediction permanently</strong>{" "}
              the moment it&apos;s made, in an append-only ledger nothing can edit
              or delete — even the system itself. That&apos;s what makes the track
              record real: there&apos;s no way to quietly fix a wrong call after the
              fact.
            </span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-black dark:text-zinc-50">4.</span>
            <span>
              <strong className="text-black dark:text-zinc-50">Grades every result automatically</strong>{" "}
              once the match ends — hits and misses alike, published either way.
            </span>
          </li>
        </ol>

        <p className="mt-8 text-zinc-600 dark:text-zinc-400">
          It all runs unattended on a self-managed Kubernetes cluster — no manual
          intervention required to keep it going.
        </p>

        <p className="mt-6 text-zinc-600 dark:text-zinc-400">
          Alongside the pipeline, <strong className="text-black dark:text-zinc-50">Petey</strong>{" "}
          answers real questions about the data — how a market has performed,
          how a team has been playing lately. Petey never writes its own
          database queries or sees raw rows: it only ever phrases a
          pre-computed, validated answer as a sentence, and it says so
          plainly when a sample is too small to trust.
        </p>

        <div className="mt-8 flex flex-wrap gap-3">
          <a href="/track-record" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            See the live track record &rarr;
          </a>
          <a href="/petey" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            Ask Petey &rarr;
          </a>
          <a href="/data-dictionary" className="inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
            Data dictionary &rarr;
          </a>
        </div>

        <p className="mt-10 text-sm text-zinc-500 dark:text-zinc-500">
          Futbol Modelo is an analytics and calibration project, not a
          gambling product. It doesn&apos;t place bets, take odds, or offer
          betting advice — every prediction exists to be graded against
          reality, nothing more.
        </p>
      </main>
    </div>
  );
}
