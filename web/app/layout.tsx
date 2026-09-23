// Root layout, kept deliberately minimal: api/ routes and the
// locale-agnostic special files (manifest.ts, robots.ts, sitemap.ts,
// feed.xml, opengraph-image.tsx, apple-icon.tsx) all live at this
// level, outside app/[locale]/, and don't need (or want) the real
// <html>/<body>/NextIntlClientProvider wrapper -- that lives in
// app/[locale]/layout.tsx, scoped to actual localized pages.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return children;
}
