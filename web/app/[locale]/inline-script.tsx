// Runs synchronously during HTML parsing, before React hydrates -- see
// local-date.tsx and node_modules/next/dist/docs/.../preventing-flash-before-hydration.md.
// type flips server->client so React doesn't warn about a stray <script>
// on client-side navigations (where it's inert -- toLocaleString runs
// directly in LocalDate's own render instead).
export function InlineScript({ html }: { html: string }) {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
