import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

interface TimelineEvent {
  seq: number;
  event_id: string;
  event_type: string;
  timestamp: number;
  metadata: Record<string, unknown>;
  chain_hash_prefix: string;
}

function proxyHeaders(req: NextRequest): Record<string, string> {
  const apiKey = req.headers.get("X-IronCore-API-Key") ?? req.headers.get("x-ironcore-api-key") ?? "";
  return {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
  };
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;

  try {
    const url = new URL(req.url);
    const query = url.searchParams.toString();
    const endpoint = query
      ? `${BACKEND_URL}/api/forensics/sessions/${encodeURIComponent(sessionId)}/timeline?${query}`
      : `${BACKEND_URL}/api/forensics/sessions/${encodeURIComponent(sessionId)}/timeline`;

    const res = await fetch(endpoint, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });

    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json([], { status: 200 });
  }
}
