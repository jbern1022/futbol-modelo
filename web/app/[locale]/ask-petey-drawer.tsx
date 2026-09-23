"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname } from "@/i18n/navigation";
import PeteyWidget from "./petey-widget";

export default function AskPeteyDrawer() {
  const t = useTranslations("AskPetey");
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  if (pathname === "/petey") return null;

  return (
    <>
      <button onClick={() => setOpen(true)} className="fixed bottom-20 right-4 z-50 rounded-full border border-zinc-300 bg-black px-4 py-2 text-sm font-medium text-white shadow-md hover:bg-zinc-800 dark:border-zinc-700 dark:bg-zinc-50 dark:text-black dark:hover:bg-zinc-200">
        {t("askPetey")}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div onClick={() => setOpen(false)} className="absolute inset-0 bg-black/30" />

          <div className="relative h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-xl dark:bg-zinc-950 sm:max-w-sm">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-black dark:text-zinc-50">
                {t("askPetey")}
              </h2>
              <button onClick={() => setOpen(false)} aria-label={t("close")} className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                &#10005;
              </button>
            </div>
            <p className="mt-1 text-sm text-zinc-500">
              {t("subtitle")}
            </p>

            <div className="mt-6">
              <PeteyWidget compact />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
