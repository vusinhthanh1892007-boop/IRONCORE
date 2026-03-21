import { NextRequest } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function proxyHeaders(req: NextRequest): Record<string, string> {
  const apiKey = req.headers.get("X-IronCore-API-Key") ?? req.headers.get("x-ironcore-api-key") ?? "";
  return {
    "Content-Type": "application/json",
    ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
  };
}

const eventTypes = ["start", "tool_call", "tool_done", "hitl_wait", "complete", "error"] as const;
const tools = ["planner.route", "runtime.exec", "memory.lookup", "hitl.request", "scheduler.run"] as const;
const agents = ["agent-alpha", "agent-bravo", "agent-charlie", "agent-delta"] as const;

function randomEventLine() {
  const type = eventTypes[Math.floor(Math.random() * eventTypes.length)];
  const agentId = agents[Math.floor(Math.random() * agents.length)];
  const tool = tools[Math.floor(Math.random() * tools.length)];
  const severity = type === "error" ? "high" : type === "hitl_wait" ? "medium" : "info";

  const payload = {
    id: `spatial-live-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    agent_id: agentId,
    event_type: type,
    tool_name: type === "tool_call" || type === "tool_done" ? tool : undefined,
    session_id: `sess-${Math.floor(Date.now() / 1000)}`,
    cost_usd: type === "tool_call" || type === "tool_done" ? Number((Math.random() * 0.008).toFixed(5)) : undefined,
    latency_ms: Math.floor(80 + Math.random() * 720),
    severity,
    timestamp: new Date().toISOString(),
  };

  return `data: ${JSON.stringify(payload)}\n\n`;
}

export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${BACKEND_URL}/api/runtime/agents/stream`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });

    if (upstream.ok && upstream.body) {
      return new Response(upstream.body, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          "X-Accel-Buffering": "no",
        },
      });
    }
  } catch {
    // fallback to synthetic stream below
  }

  let interval: ReturnType<typeof setInterval> | null = null;
  let heartbeat: ReturnType<typeof setInterval> | null = null;

  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(`event: ready\ndata: ${JSON.stringify({ ok: true, mock: true })}\n\n`));

      interval = setInterval(() => {
        controller.enqueue(new TextEncoder().encode(randomEventLine()));
      }, 1700);

      heartbeat = setInterval(() => {
        controller.enqueue(new TextEncoder().encode(`event: ping\ndata: ${Date.now()}\n\n`));
      }, 15000);
    },
    cancel() {
      if (interval) clearInterval(interval);
      if (heartbeat) clearInterval(heartbeat);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
