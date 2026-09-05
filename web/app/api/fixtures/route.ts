const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: Request) {
  const { search } = new URL(request.url);
  const res = await fetch(`${BACKEND_URL}/v1/fixtures${search}`);
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
