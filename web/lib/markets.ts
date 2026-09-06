export const MARKET_LABELS: Record<string, string> = {
  "1X2": "Match Result",
  BTTS: "Both Teams to Score",
  TOTAL_GOALS: "Total Goals",
  CORNERS: "Corners",
  SOT: "Shots on Target",
  PLAYER_GOALS: "Anytime Goalscorer",
  PLAYER_SAVES: "Goalkeeper Saves",
  MONEYLINE: "Moneyline",
  SPREAD: "Spread",
  TOTAL_POINTS: "Total Points",
  PLAYER_POINTS: "Player Points",
};

export function marketLabel(market: string): string {
  return MARKET_LABELS[market] || market;
}
