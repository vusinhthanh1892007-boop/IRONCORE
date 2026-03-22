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

export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${BACKEND_URL}/api/enterprise/siem/stream`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });

    if (upstream.ok && upstream.body) {
      return new Response(upstream.body, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
          "X-Accel-Buffering": "no",
        },
      });
    }
  } catch {
    // no-op: return an empty SSE stream below
  }

  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(
          `event: ready\ndata: ${JSON.stringify({ ok: true, empty: true })}\n\n`
        )
      );
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
