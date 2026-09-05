import Link from "next/link";

export default function LessonsLearnedPage() {
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Lessons Learned
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          A real build has real bugs. Here are the ones worth telling — not
          because they were dramatic, but because of what they kept teaching
          the same lesson about, over and over: the gap between{" "}
          <em>believing</em> something works and actually{" "}
          <em>verifying</em> it does.
        </p>

        <div className="mt-10 space-y-10">
          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              A uniqueness constraint that never enforced uniqueness
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              Early on, the prediction ledger had a standard SQL{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-sm dark:bg-zinc-900">
                UNIQUE
              </code>{" "}
              constraint meant to stop the same prediction from ever being
              written twice. It looked correct in every code review. It
              wasn&apos;t. SQL treats{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-sm dark:bg-zinc-900">
                NULL
              </code>{" "}
              as never equal to anything &mdash; including another{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-sm dark:bg-zinc-900">
                NULL
              </code>
              . Since every market has at least one nullable subject column
              (a team-level prediction has no player, a player-level
              prediction has no team), the constraint silently never
              deduplicated anything, for any market, from day one. The fix
              was an expression-based index using{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-sm dark:bg-zinc-900">
                COALESCE
              </code>{" "}
              instead. The real lesson wasn&apos;t about SQL syntax &mdash;
              it was that a constraint existing in the schema isn&apos;t the
              same thing as a constraint actually working.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              Petey reads a percentage as a body count
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              The first time Petey answered a real question about a market
              with a 0% hit rate, it said: &ldquo;we didn&apos;t score any
              goals in the tournament.&rdquo; Nothing was scored, literally
              &mdash; it read a stated confidence number as a count of
              real-world events. The fix was a clearer prompt explaining
              what &ldquo;hit rate&rdquo; actually means. That held for
              exactly one more bug: even with careful instructions not to
              editorialize, Petey kept describing neutral numbers as
              &ldquo;struggled,&rdquo; &ldquo;moderate,&rdquo;
              &ldquo;steady&rdquo; &mdash; none of them grounded in
              anything it was actually given. Asking the model more
              politely didn&apos;t hold. What did: a structural filter that
              throws away any answer containing an unsupported judgment
              word and falls back to a plain, deterministic sentence
              instead. Safety through architecture, not through a
              better-worded request.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              A hostname that only existed inside the cluster
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              Petey worked perfectly in every local test. It failed
              completely the moment it went live. The reason: the
              frontend&apos;s API calls were pointed at Kubernetes&apos;
              internal service name for the backend &mdash; a hostname that
              only resolves <em>inside</em>{" "}the cluster&apos;s own network.
              A real browser, out on the public internet, has no way to
              look that up. Every server-rendered page worked fine, because
              those requests run from inside a pod. Only the
              browser-side requests broke. The fix was routing those calls
              through small Next.js API routes that run server-side and
              proxy to the real backend &mdash; the same pattern every other
              working page already used, just not yet applied to the one
              page built differently.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
              Fixed, tested, shipped &mdash; except it wasn&apos;t
            </h2>
            <p className="mt-2 text-zinc-600 dark:text-zinc-400">
              This is the one worth sitting with. Two separate fixes were
              built, verified in isolation, and genuinely believed to be
              live: a corners/shots statement rewrite so predictions read
              clearly per team instead of ambiguously, and an out-of-fold
              isotonic calibration layer built specifically to correct a
              confirmed overconfidence problem in the corners model. Both
              were reported, at the time, as done. Neither one had actually
              been wired into the script the real nightly pipeline runs.
              The calibration code sat in a validated, working training
              script for weeks while live predictions kept shipping on raw,
              uncorrected probabilities. Nobody caught it because nothing
              was <em>wrong</em>{" "}in an obviously visible way &mdash; the
              predictions still looked reasonable, the site still worked,
              the commit messages read like a finished feature. It took
              directly grepping the actual file the CronJob executes,
              rather than trusting memory or a past summary, to find out.
              That&apos;s the real habit this project reinforced: the only
              thing that confirms a fix works is checking the code that
              actually runs in production &mdash; not the code that was
              written, not what a commit message claims, not what was
              believed the last time someone looked.
            </p>
          </section>
        </div>

        <p className="mt-10 text-zinc-600 dark:text-zinc-400">
          None of these were caught by getting smarter about writing bugs.
          They were caught by building the discipline to keep checking
          &mdash; against real data, real running code, real production
          behavior &mdash; instead of trusting that something already
          confirmed once will still be true later.
        </p>

        <a href="/how-it-works" className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900">
          How it works &rarr;
        </a>
      </main>
    </div>
  );
}
