import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

// Locale-aware Link/useRouter/redirect -- use these instead of
// next/link and next/navigation everywhere a link should carry the
// current locale (e.g. an English visitor's links all stay
// unprefixed, a Spanish visitor's all carry /es).
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
