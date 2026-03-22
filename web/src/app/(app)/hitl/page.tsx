"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";

interface HitlRequest {
  id: string;
  action_type: string;
  description: string;
  risk_level: "low" | "medium" | "high" | "critical";
  requested_by: string;
  session_id: string;
  created_at: string;
  expires_at: string;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired" | "auto_approved";
}

const riskBadgeClass: Record<HitlRequest["risk_level"], string> = {
  critical: "bg-red-500/20 text-red-500 border-red-500/30",
  high: "bg-orange-500/20 text-orange-500 border-orange-500/30",
  medium: "bg-yellow-500/20 text-yellow-600 border-yellow-500/30",
  low: "bg-green-500/20 text-green-600 border-green-500/30",
};

function normalize(raw: unknown): HitlRequest[] {
  if (!Array.isArray(raw)) return [];
  const items: HitlRequest[] = [];

  for (const item of raw) {
    const row = (item ?? {}) as Record<string, unknown>;
    const id = String(row.id ?? row.ticket_id ?? "");
    if (!id) continue;

    const created = row.created_at;
    const expires = row.expires_at;

    const createdAt =
      typeof created === "number"
        ? new Date(created * 1000).toISOString()
        : typeof created === "string"
          ? created
          : new Date().toISOString();

    const expiresAt =
      typeof expires === "number"
        ? new Date(expires * 1000).toISOString()
        : typeof expires === "string"
          ? expires
          : new Date(Date.now() + 60_000).toISOString();

    const risk = String(row.risk_level ?? "medium").toLowerCase();
    const riskLevel: HitlRequest["risk_level"] =
      risk === "critical" || risk === "high" || risk === "medium" || risk === "low"
        ? (risk as HitlRequest["risk_level"])
        : "medium";

    items.push({
      id,
      action_type: String(row.action_type ?? "unknown_action"),
      description: String(row.description ?? row.risk_reason ?? "No description"),
      risk_level: riskLevel,
      requested_by: String(row.requested_by ?? row.requestor_id ?? "unknown"),
      session_id: String(row.session_id ?? ""),
      created_at: createdAt,
      expires_at: expiresAt,
      payload:
        row.payload && typeof row.payload === "object"
          ? (row.payload as Record<string, unknown>)
          : row.action_payload && typeof row.action_payload === "object"
            ? (row.action_payload as Record<string, unknown>)
            : {},
      status: "pending",
    });
  }

  return items.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
}

function formatSla(expiresAt: string) {
  const diffSec = Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000);
  if (diffSec <= 0) return { label: "Expired", urgent: true };
  const m = Math.floor(diffSec / 60);
  const s = diffSec % 60;
  return { label: `${m}:${String(s).padStart(2, "0")}`, urgent: diffSec < 30 };
}

export default function HitlApprovalPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string>("");
  const [rejectReason, setRejectReason] = React.useState("");
  const seenIdsRef = React.useRef<Set<string>>(new Set());
  const [nowTick, setNowTick] = React.useState(0);

  React.useEffect(() => {
    const timer = window.setInterval(() => setNowTick((v) => v + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const pendingQuery = useQuery({
    queryKey: ["hitl-pending"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/hitl/pending", { cache: "no-store" });
      if (!res.ok) throw new Error("HITL pending unavailable");
      return normalize(await res.json());
    },
    refetchInterval: 3_000,
    retry: 0,
  });

  const pending = React.useMemo(() => pendingQuery.data ?? [], [pendingQuery.data]);

  React.useEffect(() => {
    const oldSet = seenIdsRef.current;
    const currentIds = new Set(pending.map((r) => r.id));

    for (const req of pending) {
      if (!oldSet.has(req.id)) {
        toast.info(`New HITL request: ${req.action_type} (${req.id})`);
      }
    }

    for (const previous of oldSet) {
      if (!currentIds.has(previous)) {
        toast.warning(`Request ${previous} expired or decided.`);
      }
    }

    seenIdsRef.current = currentIds;
  }, [pending]);

  React.useEffect(() => {
    if (pending.length === 0) {
      setSelectedId("");
      return;
    }
    if (!selectedId || !pending.some((row) => row.id === selectedId)) {
      setSelectedId(pending[0].id);
    }
  }, [pending, selectedId]);

  const selected = pending.find((row) => row.id === selectedId) ?? null;

  const decide = async (decision: "approve" | "reject" | "escalate", request: HitlRequest, reason = "") => {
    if (decision === "reject" && !reason.trim()) {
      toast.error("Reject reason is required.");
      return;
    }

    const payload: Record<string, string> = {
      decided_by: "operator.web",
    };
    if (reason.trim()) payload.reason = reason.trim();

    try {
      const res = await fetch(`/api/enterprise/hitl/${request.id}/${decision}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: "Decision failed" }));
        throw new Error(String(err.message ?? "Decision failed"));
      }

      const label =
        decision === "approve"
          ? "Approved"
          : decision === "reject"
            ? "Rejected"
            : "Escalated";
      toast.success(`${label} ${request.id}`);
      setRejectReason("");
      queryClient.invalidateQueries({ queryKey: ["hitl-pending"] });
      queryClient.invalidateQueries({ queryKey: ["hitl-history"] });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Decision failed");
    }
  };

  void nowTick;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">HITL Approval Dashboard</h1>
          <p className="text-sm text-muted-foreground">Duyệt hoặc từ chối các hành động rủi ro theo thời gian thực.</p>
        </div>
        <Badge className="bg-red-500/20 text-red-500 border-red-500/30">Pending: {pending.length}</Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="border border-border bg-card p-4">
          <div className="mb-3 text-sm font-semibold">Pending Queue</div>
          <div className="space-y-2">
            {pending.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">No pending HITL requests.</div>
            ) : (
              pending.map((req) => {
                const sla = formatSla(req.expires_at);
                const active = req.id === selectedId;
                return (
                  <button
                    key={req.id}
                    type="button"
                    onClick={() => setSelectedId(req.id)}
                    onDoubleClick={() => void decide("approve", req)}
                    className={`w-full rounded-lg border p-3 text-left transition ${
                      active ? "border-foreground/40 bg-muted/60" : "border-border hover:bg-muted/50"
                    }`}
                  >
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <div className="text-sm font-medium">{req.action_type}</div>
                      <span className={`rounded-full border px-2 py-0.5 text-xs ${riskBadgeClass[req.risk_level]}`}>{req.risk_level}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">{req.requested_by} · {req.id}</div>
                    <div className="mt-2 flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">SLA</span>
                      <span className={sla.urgent ? "font-semibold text-red-500" : "text-foreground"}>{sla.label}</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </Card>

        <Card className="border border-border bg-card p-4">
          <div className="mb-3 text-sm font-semibold">Request Detail</div>
          {!selected ? (
            <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">Select a request from queue.</div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${riskBadgeClass[selected.risk_level]}`}>{selected.risk_level}</span>
                  <span className="text-xs text-muted-foreground">{selected.id}</span>
                </div>
                <div className="text-sm font-medium">{selected.description}</div>
                <div className="text-xs text-muted-foreground">Requester: {selected.requested_by}</div>
              </div>

              <details className="rounded-lg border border-border p-3" open>
                <summary className="cursor-pointer text-sm font-medium">Payload (JSON)</summary>
                <pre className="mt-2 overflow-auto rounded bg-muted p-2 text-xs">
{JSON.stringify(selected.payload, null, 2)}
                </pre>
              </details>

              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>Created: {new Date(selected.created_at).toLocaleString()}</span>
                <span>·</span>
                <span>Expires: {new Date(selected.expires_at).toLocaleString()}</span>
              </div>

              <Link href={`/chat/${selected.session_id}`} className="text-sm text-primary underline underline-offset-4">
                See session context
              </Link>

              <div className="space-y-2">
                <Textarea
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Reason (required for reject)"
                  className="min-h-[90px]"
                />
                <div className="flex flex-wrap gap-2">
                  <Button className="bg-green-600 hover:bg-green-600/90" onClick={() => void decide("approve", selected)}>
                    Approve
                  </Button>
                  <Button variant="outline" onClick={() => void decide("escalate", selected, rejectReason)}>
                    Escalate
                  </Button>
                  <Button variant="destructive" onClick={() => void decide("reject", selected, rejectReason)}>
                    Reject
                  </Button>
                </div>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
