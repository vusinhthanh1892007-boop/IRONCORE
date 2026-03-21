import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ALLOWED = new Set(["pause", "resume", "trigger"]);

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

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ jobId: string; action: string }> }
) {
  try {
    const { jobId, action } = await params;
    if (!ALLOWED.has(action)) {
      return NextResponse.json({ error: "Invalid action" }, { status: 400 });
    }
    const res = await fetch(`${BACKEND_URL}/api/scheduler/jobs/${jobId}/${action}`, {
      method: "POST",
      headers: proxyHeaders(req),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { message: "Scheduler backend unavailable." },
      { status: 503 }
    );
  }
}
