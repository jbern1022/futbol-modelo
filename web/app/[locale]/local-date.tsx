"use client";

import { useId } from "react";
import { InlineScript } from "./inline-script";

// A UTC timestamp renders differently depending on the viewer's locale
// and time zone, which the server can't know -- toLocaleDateString/
// toLocaleString on the server (Node, whatever locale/TZ that
// container runs) legitimately produces different text than the same
// call in the visiting browser, which is a real hydration mismatch,
// not a bug in the data. An inline script corrects the DOM before the
// browser's first paint (no flash), and suppressHydrationWarning tells
// React to accept that corrected DOM instead of discarding it -- see
// node_modules/next/dist/docs/.../preventing-flash-before-hydration.md,
// which this component follows directly.
export function LocalDate({
  date,
  mode = "date",
  options,
  className,
}: {
  date: string;
  mode?: "date" | "datetime";
  options?: Intl.DateTimeFormatOptions;
  className?: string;
}) {
  const id = useId();
  const method = mode === "datetime" ? "toLocaleString" : "toLocaleDateString";
  const text =
    mode === "datetime"
      ? new Date(date).toLocaleString(undefined, options)
      : new Date(date).toLocaleDateString(undefined, options);

  return (
    <>
      <time id={id} dateTime={date} suppressHydrationWarning className={className}>
        {text}
      </time>
      <InlineScript
        html={`{var n=document.getElementById("${id}");if(n)n.textContent=new Date("${date}").${method}(undefined,${JSON.stringify(options ?? {})})}`}
      />
    </>
  );
}
