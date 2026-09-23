"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";

const NAV_HREFS = ["/", "/standings", "/track-record"] as const;

export default function NavLinks() {
  const pathname = usePathname();
  const t = useTranslations("Nav");

  return (
    <nav className="flex items-center gap-5">
      {NAV_HREFS.map((href) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={
              active
                ? "text-sm font-medium text-black dark:text-zinc-50"
                : "text-sm text-zinc-500 hover:text-black dark:hover:text-zinc-50 transition-colors"
            }
          >
            {href === "/" ? t("fixtures") : href === "/standings" ? t("standings") : t("trackRecord")}
          </Link>
        );
      })}
    </nav>
  );
}
