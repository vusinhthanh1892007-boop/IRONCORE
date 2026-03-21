import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

const fallbackUsers = [
  { username: "alex", email: "alex@ironcore.ai", roles: ["admin", "approver"], last_login: new Date(Date.now() - 3600 * 1000).toISOString(), status: "active" },
  { username: "kim", email: "kim@ironcore.ai", roles: ["operator"], last_login: new Date(Date.now() - 6 * 3600 * 1000).toISOString(), status: "active" },
  { username: "lee", email: "lee@ironcore.ai", roles: ["auditor"], last_login: new Date(Date.now() - 2 * 24 * 3600 * 1000).toISOString(), status: "disabled" },
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
    const res = await fetch(`${BACKEND_URL}/api/enterprise/iam/users`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(fallbackUsers, { status: 200 });
  }
}
