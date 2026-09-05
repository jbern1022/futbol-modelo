"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import PeteyWidget from "../petey-widget";

function PeteyPageInner() {
  const searchParams = useSearchParams();
  const initialTeam = searchParams.get("team") || "";
  const initialLeague = searchParams.get("league") || "MLS";
  const initialMode: "accuracy" | "form" =
    searchParams.get("mode") === "form" || initialTeam ? "form" : "accuracy";

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; Back to fixtures
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Ask Petey
        </h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Real questions, real data — including when a sample is too small
          to trust.
        </p>

        <div className="mt-6">
          <PeteyWidget
            initialTeam={initialTeam}
            initialLeague={initialLeague}
            initialMode={initialMode}
          />
        </div>
      </main>
    </div>
  );
}

export default function PeteyPage() {
  return (
    <Suspense fallback={null}>
      <PeteyPageInner />
    </Suspense>
  );
}
