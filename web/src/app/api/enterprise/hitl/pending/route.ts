import { NextRequest, NextResponse } from "next/server";
import { listPendingMock, replacePendingMock } from "../_mockStore";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

function proxyHeaders(req: NextRequest): Record<string, string> {
  const apiKey =
    req.headers.get("X-IronCore-API-Key") ??
    req.headers.get("x-ironcore-api-key") ??
    "";

  return {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
  };
}

export async function GET(req: NextRequest) {
  try {
    const res = await fetch(`${BACKEND_URL}/api/enterprise/hitl/pending`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    const now = Date.now();
    const active = listPendingMock().filter((item) => new Date(item.expires_at).getTime() > now);
    const expired = listPendingMock().filter((item) => new Date(item.expires_at).getTime() <= now);
    if (expired.length > 0) {
      replacePendingMock(active);
    }
    return NextResponse.json(active, { status: 200 });
  }
}
