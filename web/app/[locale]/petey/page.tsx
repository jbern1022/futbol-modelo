"use client";

import { Suspense } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useSearchParams } from "next/navigation";
import PeteyWidget from "../petey-widget";

function PeteyPageInner() {
  const t = useTranslations("AskPetey");
  const searchParams = useSearchParams();
  const initialTeam = searchParams.get("team") || "";
  const initialLeague = searchParams.get("league") || "MLS";
  const initialMode: "accuracy" | "form" =
    searchParams.get("mode") === "form" || initialTeam ? "form" : "accuracy";

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          &larr; {t("backToFixtures")}
        </Link>

        <h1 className="mt-6 text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          {t("askPetey")}
        </h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          {t("subtitle")}
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
