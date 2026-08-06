/**
 * Shared header and footer.
 *
 * Navigation previously existed only on the homepage: Track Record and Petey
 * each offered a single "back to fixtures" link, and the fixture page — the
 * one someone actually reads predictions on — had no route to Track Record at
 * all. The calibration story was unreachable from the place it matters most.
 */

const NAV = [
  { href: "/", label: "Fixtures" },
  { href: "/track-record", label: "Track Record" },
  { href: "/petey", label: "Ask Petey" },
  { href: "/how-it-works", label: "How It Works" },
];

export function SiteHeader() {
  return (
    <header className="border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-black/80">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-4xl flex-wrap items-center gap-x-4 gap-y-2 px-6 py-3"
      >
        <a href="/" className="text-sm font-semibold tracking-tight text-black dark:text-zinc-50">
          Futbol Modelo
        </a>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {NAV.slice(1).map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm text-zinc-600 hover:text-black dark:text-zinc-400 dark:hover:text-zinc-50"
            >
              {item.label}
            </a>
          ))}
        </div>
      </nav>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto max-w-4xl px-6 py-8 text-xs leading-relaxed text-zinc-500">
        <p>
          Predictions are written to an append-only ledger before kickoff and
          graded automatically once each match finishes. Nothing is edited or
          removed after the fact, including the misses.
        </p>
        <p className="mt-3">
          Match data from{" "}
          <a href="https://fbref.com" className="underline hover:no-underline">FBref</a>,{" "}
          <a href="https://understat.com" className="underline hover:no-underline">Understat</a>{" "}
          and{" "}
          <a href="https://www.api-football.com" className="underline hover:no-underline">API-Football</a>.
        </p>
        <p className="mt-3 text-zinc-400 dark:text-zinc-600">
          An analytics project, not a wagering tool. No affiliate links, no tips
          for sale.
        </p>
      </div>
    </footer>
  );
}
