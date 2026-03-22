import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

interface ForensicsSessionItem {
  session_id: string;
  started_at: number;
  ended_at?: number | null;
  event_count: number;
  primary_agent: string;
}

const now = Date.now();

const fallbackSessions: ForensicsSessionItem[] = [
  {
    session_id: "sess-forensics-001",
    started_at: Math.floor((now - 1000 * 60 * 38) / 1000),
    ended_at: Math.floor((now - 1000 * 60 * 30) / 1000),
    event_count: 24,
    primary_agent: "agent-alpha",
  },
  {
    session_id: "sess-forensics-002",
    started_at: Math.floor((now - 1000 * 60 * 22) / 1000),
    ended_at: Math.floor((now - 1000 * 60 * 8) / 1000),
    event_count: 19,
    primary_agent: "agent-bravo",
  },
  {
    session_id: "sess-forensics-003",
    started_at: Math.floor((now - 1000 * 60 * 10) / 1000),
    ended_at: null,
    event_count: 12,
    primary_agent: "agent-charlie",
  },
];

function proxyHeaders(req: NextRequest): Record<string, string> {
  const apiKey = req.headers.get("X-IronCore-API-Key") ?? req.headers.get("x-ironcore-api-key") ?? "";
  return {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
  };
}

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const query = url.searchParams.toString();
    const endpoint = query
      ? `${BACKEND_URL}/api/forensics/sessions?${query}`
      : `${BACKEND_URL}/api/forensics/sessions`;

    const res = await fetch(endpoint, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });

    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(fallbackSessions, { status: 200 });
  }
}
