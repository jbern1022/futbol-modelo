const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const league = searchParams.get("league");
  const url = league
    ? `${BACKEND_URL}/v1/teams?league=${encodeURIComponent(league)}`
    : `${BACKEND_URL}/v1/teams`;
  const res = await fetch(url);
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
