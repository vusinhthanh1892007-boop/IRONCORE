import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

const fallbackMappings = [
  { id: "map-1", provider: "azure_entra", group: "IT-Admins", role: "admin" },
  { id: "map-2", provider: "okta", group: "RiskManagement", role: "approver" },
  { id: "map-3", provider: "oidc", group: "SOC-Team", role: "auditor" },
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
    const res = await fetch(`${BACKEND_URL}/api/enterprise/iam/sso-mappings`, {
      headers: proxyHeaders(req),
      cache: "no-store",
    });
    const data = await res.json().catch(() => []);
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(fallbackMappings, { status: 200 });
  }
}
