import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

const fallbackRoles = [
  { role_name: "admin", permissions: ["*"], users_count: 2 },
  { role_name: "approver", permissions: ["hitl.approve", "hitl.reject"], users_count: 3 },
  { role_name: "operator", permissions: ["runtime.read", "sessions.manage"], users_count: 6 },
  { role_name: "auditor", permissions: ["siem.read", "forensics.export"], users_count: 2 },
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
    const res = await fetch(`${BACKEND_URL}/api/enterprise/iam/roles`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(fallbackRoles, { status: 200 });
  }
}
