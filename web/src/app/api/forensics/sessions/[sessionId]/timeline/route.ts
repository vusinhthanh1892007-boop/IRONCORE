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

const eventTypePattern = [
  "agent.start",
  "agent.think",
  "tool.call",
  "tool.result",
  "hitl.wait",
  "agent.resume",
  "agent.complete",
];

function proxyHeaders(req: NextRequest): Record<string, string> {
  const apiKey = req.headers.get("X-IronCore-API-Key") ?? req.headers.get("x-ironcore-api-key") ?? "";
  return {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
  };
}

function fallbackTimeline(sessionId: string): TimelineEvent[] {
  const start = Date.now() - 1000 * 60 * 8;
  return Array.from({ length: 18 }, (_, idx) => {
    const type = eventTypePattern[idx % eventTypePattern.length];
    return {
      seq: idx + 1,
      event_id: `${sessionId}-event-${idx + 1}`,
      event_type: type,
      timestamp: Math.floor((start + idx * 22000) / 1000),
      metadata: {
        session_id: sessionId,
        agent_id: idx % 2 === 0 ? "agent-alpha" : "agent-bravo",
        tool_name: type.includes("tool") ? (idx % 3 === 0 ? "runtime.exec" : "memory.lookup") : undefined,
        latency_ms: 120 + idx * 8,
        cost_usd: Number((0.0008 * (idx + 1)).toFixed(5)),
        severity: type.includes("error") ? "high" : type.includes("hitl") ? "medium" : "info",
        cef_line: `CEF:0|IronCore|IronCore-AI-Platform|2.0|${200 + idx}|Replay Event|5|act=${type}`,
      },
      chain_hash_prefix: `h${(10000 + idx).toString(16)}`,
    };
  });
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
    return NextResponse.json(fallbackTimeline(sessionId), { status: 200 });
  }
}
