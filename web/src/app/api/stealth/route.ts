import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function backendHeaders(req: NextRequest) {
  return {
    "Content-Type": "application/json",
    "X-IronCore-API-Key":
      req.headers.get("X-IronCore-API-Key") ??
      req.headers.get("x-ironcore-api-key") ??
      "",
  };
}

/** GET /api/stealth – proxy to GET /v1/stealth/status */
export async function GET(req: NextRequest) {
  const res = await fetch(`${BACKEND_URL}/v1/stealth/status`, {
    headers: backendHeaders(req),
    cache: "no-store",
  }).catch((e) => {
    throw new Error(`Backend unreachable: ${e.message}`);
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

/** POST /api/stealth – dispatch screenshot or scrape task */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({})) as {
    task?: "screenshot" | "scrape";
    url?: string;
    wait_ms?: number;
    full_page?: boolean;
    selector?: string;
  };

  const { task = "screenshot", ...rest } = body;

  if (!rest.url) {
    return NextResponse.json({ error: "url is required" }, { status: 400 });
  }

  const endpoint = task === "scrape" ? "scrape" : "screenshot";

  const res = await fetch(`${BACKEND_URL}/v1/stealth/${endpoint}`, {
    method: "POST",
    headers: backendHeaders(req),
    body: JSON.stringify(rest),
  }).catch((e) => {
    throw new Error(`Backend unreachable: ${e.message}`);
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
