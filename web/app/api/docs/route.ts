const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// /docs-public, not /docs -- FastAPI's default /docs hardcodes
// openapi_url="/openapi.json", which resolves wrong once proxied
// under /api/docs. /docs-public is generated with openapi_url set to
// /api/openapi.json instead, so it works through this proxy. See
// api/main.py's public_docs().
export async function GET() {
  const res = await fetch(`${BACKEND_URL}/docs-public`);
  return new Response(res.body, {
    status: res.status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}
