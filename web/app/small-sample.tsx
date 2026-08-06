/**
 * ADR-007: one shared small-sample disclaimer, same trigger and same copy
 * wherever a rate is shown. The ADR is explicit that this belongs in both
 * Petey's answers and the Track Record page; it had only ever been applied to
 * Petey, so a figure computed from 3 predictions rendered on Track Record with
 * exactly the same authority as one computed from 300.
 *
 * The threshold is deliberately provisional — ADR-007 starts at n < 5 and
 * expects to revisit it against real usage. Keeping it here means raising it
 * is a one-line change that moves every surface at once.
 */
export const SMALL_SAMPLE_THRESHOLD = 5;

export function isSmallSample(n: number | null | undefined): boolean {
  return typeof n === "number" && n < SMALL_SAMPLE_THRESHOLD;
}

export function smallSampleText(n: number, noun = "prediction"): string {
  return `Based on only ${n} ${noun}${n === 1 ? "" : "s"} — treat this cautiously.`;
}

/** Full-width note, for answers and panels. */
export function SmallSampleNote({
  n,
  noun = "prediction",
  className = "",
}: {
  n: number;
  noun?: string;
  className?: string;
}) {
  return (
    <p className={`text-sm text-amber-700 dark:text-amber-400 ${className}`}>
      &#9888; {smallSampleText(n, noun)}
    </p>
  );
}

/** Compact inline marker, for table rows where a sentence would not fit. */
export function SmallSampleBadge({ n, noun = "prediction" }: { n: number; noun?: string }) {
  return (
    <span
      title={smallSampleText(n, noun)}
      className="ml-1.5 inline-flex items-center rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800 dark:bg-amber-950 dark:text-amber-300"
    >
      small sample
    </span>
  );
}
