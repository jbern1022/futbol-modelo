const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://futbol-api-svc:8000";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const league = searchParams.get("league");
  const url = league
    ? `${BACKEND_URL}/teams?league=${encodeURIComponent(league)}`
    : `${BACKEND_URL}/teams`;
  const res = await fetch(url);
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
