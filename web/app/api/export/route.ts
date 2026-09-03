const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const league = searchParams.get("league");
  const url = league
    ? `${BACKEND_URL}/v1/export/predictions.csv?league=${encodeURIComponent(league)}`
    : `${BACKEND_URL}/v1/export/predictions.csv`;
  const res = await fetch(url);
  return new Response(res.body, {
    status: res.status,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": "attachment; filename=futbol-modelo-predictions.csv",
    },
  });
}
