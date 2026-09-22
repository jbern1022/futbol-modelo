export const SPORT_LABELS: Record<string, string> = {
  soccer: "Soccer",
  football: "Football (NFL)",
  basketball: "Basketball (NBA)",
};

export function sportLabel(sport: string): string {
  return SPORT_LABELS[sport] || sport;
}
