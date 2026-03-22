import { NextRequest, NextResponse } from "next/server";

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
    const res = await fetch(`${BACKEND_URL}/api/scheduler/jobs`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { message: "Scheduler backend unavailable." },
      { status: 503 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const payload = {
      job_id: body.name,
      name: body.name,
      cron_expression: body.cron_expression,
      task_type: body.task_type ?? "built_in",
      task_config: body.task_config ?? {},
    };
    const res = await fetch(`${BACKEND_URL}/api/scheduler/jobs`, {
      method: "POST",
      headers: proxyHeaders(req),
      body: JSON.stringify(payload),
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
