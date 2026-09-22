export const MARKET_LABELS: Record<string, string> = {
  "1X2": "Match Result",
  BTTS: "Both Teams to Score",
  TOTAL_GOALS: "Total Goals",
  CORNERS: "Corners",
  SOT: "Shots on Target",
  CARDS: "Cards",
  PLAYER_GOALS: "Anytime Goalscorer",
  PLAYER_SAVES: "Goalkeeper Saves",
  MONEYLINE: "Moneyline",
  SPREAD: "Spread",
  TOTAL_POINTS: "Total Points",
  PLAYER_POINTS: "Player Points",
  PLAYER_PASS_YARDS: "Passing Yards",
  PLAYER_RUSH_YARDS: "Rushing Yards",
};

export function marketLabel(market: string): string {
  return MARKET_LABELS[market] || market;
}
