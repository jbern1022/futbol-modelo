import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Everything except api/, Next internals, and static/metadata files
  // that must stay at their exact existing paths (favicon, manifest,
  // sitemap, robots, RSS feed, opengraph images) -- those are either
  // locale-agnostic or already handled by their own root-level route.
  matcher: [
    "/((?!api|_next|_vercel|favicon.ico|icon.svg|manifest.webmanifest|robots.txt|sitemap.xml|feed.xml|opengraph-image|apple-icon|.*\\..*).*)",
  ],
};
