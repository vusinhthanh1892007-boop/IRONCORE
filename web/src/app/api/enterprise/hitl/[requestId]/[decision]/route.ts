import { NextRequest, NextResponse } from "next/server";
import {
  listPendingMock,
  replacePendingMock,
  prependHistoryMock,
  type HitlRequest,
} from "../../_mockStore";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ALLOWED = new Set(["approve", "reject", "escalate"]);

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

function createHistoryEntry(
  req: HitlRequest,
  decision: "approve" | "reject" | "escalate",
  reason: string,
  decidedBy: string
) {
  const duration = Math.max(0, Math.floor((Date.now() - new Date(req.created_at).getTime()) / 1000));
  return {
    id: `DEC-${Math.floor(Date.now() / 1000)}`,
    request_id: req.id,
    action_type: req.action_type,
    decided_by: decidedBy,
    decision: decision === "approve" ? "approved" : decision === "reject" ? "rejected" : "escalated",
    reason,
    duration_seconds: duration,
    timestamp: new Date().toISOString(),
    requested_by: req.requested_by,
  } as const;
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ requestId: string; decision: string }> }
) {
  const { requestId, decision } = await params;

  if (!ALLOWED.has(decision)) {
    return NextResponse.json({ error: "Invalid decision" }, { status: 400 });
  }

  const body = await req.json().catch(() => ({}));

  try {
    const backendPath =
      decision === "approve" ? "approve" : decision === "reject" ? "reject" : "escalate";
    const res = await fetch(`${BACKEND_URL}/api/enterprise/hitl/${requestId}/${backendPath}`, {
      method: "POST",
      headers: proxyHeaders(req),
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch {
    const pending = listPendingMock();
    const item = pending.find((entry) => entry.id === requestId);
    if (!item) {
      return NextResponse.json({ error: "Request not found" }, { status: 404 });
    }

    const remaining = pending.filter((entry) => entry.id !== requestId);
    replacePendingMock(remaining);

    const decidedBy = typeof body.decided_by === "string" && body.decided_by.trim() ? body.decided_by.trim() : "operator.local";
    const reason = typeof body.reason === "string" ? body.reason : "";
    prependHistoryMock(createHistoryEntry(item, decision as "approve" | "reject" | "escalate", reason, decidedBy));

    return NextResponse.json({ ok: true }, { status: 200 });
  }
}
