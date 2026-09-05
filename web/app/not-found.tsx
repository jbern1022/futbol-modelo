import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Not found
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          Whatever you were looking for isn&apos;t here — the match may not
          exist, or the link may be out of date.
        </p>
        <Link
          href="/"
          className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          &larr; Back to fixtures
        </Link>
      </main>
    </div>
  );
}
