"use client";

import { useLocale } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

const LOCALE_LABELS: Record<string, string> = { en: "EN", es: "ES" };

export default function LocaleSwitcher() {
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div role="group" aria-label="Choose language" className="flex items-center gap-1 text-xs">
      {routing.locales.map((l) => (
        <button
          key={l}
          onClick={() => router.replace(pathname, { locale: l })}
          aria-pressed={locale === l}
          aria-label={l === "en" ? "English" : "Español"}
          className={`rounded px-1.5 py-0.5 font-medium ${
            locale === l
              ? "text-black dark:text-zinc-50"
              : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
          }`}
        >
          {LOCALE_LABELS[l]}
        </button>
      ))}
    </div>
  );
}
