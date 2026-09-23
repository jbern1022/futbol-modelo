import { defineRouting } from "next-intl/routing";

// localePrefix "as-needed": English (the default, and this site's
// original/only locale until now) keeps its existing un-prefixed URLs
// (/, /track-record, ...) -- real backlinks, the RSS feed, and search
// indexing all already point at those. Spanish gets /es/... prefixed.
// Adding a locale must never break a URL that already existed.
export const routing = defineRouting({
  locales: ["en", "es"],
  defaultLocale: "en",
  localePrefix: "as-needed",
});
