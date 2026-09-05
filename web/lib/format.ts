function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

/** Renders a 0-1 probability as a plain-language ratio, e.g. 0.613 -> "roughly 3 in 5". */
export function plainOdds(probability: number): string {
  const tenths = Math.round(probability * 10);
  if (tenths <= 0) return "very unlikely";
  if (tenths >= 10) return "nearly certain";
  const d = gcd(tenths, 10);
  return `roughly ${tenths / d} in ${10 / d}`;
}
