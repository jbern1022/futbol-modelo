"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Fixtures" },
  { href: "/track-record", label: "Track Record" },
];

export default function NavLinks() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-5">
      {NAV_LINKS.map(({ href, label }) => {
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
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
