const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://futbol-api-svc:8000";

export async function POST(request: Request) {
  const body = await request.json();
  const res = await fetch(`${BACKEND_URL}/ask/team-form`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
