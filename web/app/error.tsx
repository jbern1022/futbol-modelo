"use client";

import { useEffect } from "react";

export default function Error({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Something went wrong
        </h1>
        <p className="mt-4 text-zinc-600 dark:text-zinc-400">
          The page couldn&apos;t load. This is usually temporary — the
          predictions themselves are unaffected either way.
        </p>
        <button
          onClick={() => unstable_retry()}
          className="mt-8 inline-block rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
        >
          Try again
        </button>
      </main>
    </div>
  );
}
