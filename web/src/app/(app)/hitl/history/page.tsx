"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface HitlDecision {
  id: string;
  request_id: string;
  action_type: string;
  decided_by: string;
  decision: "approved" | "rejected" | "escalated";
  reason: string;
  duration_seconds: number;
  timestamp: string;
  requested_by: string;
}

function normalizeHistory(raw: unknown): HitlDecision[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      const row = (item ?? {}) as Record<string, unknown>;
      const decisionValue = String(row.decision ?? row.status ?? "").toLowerCase();
      if (decisionValue !== "approved" && decisionValue !== "rejected" && decisionValue !== "escalated") return null;

      const id = String(row.id ?? `${row.request_id ?? "REQ"}-${row.timestamp ?? Date.now()}`);
      const durationRaw = row.duration_seconds ?? row.duration ?? 0;
      const duration = typeof durationRaw === "number" ? durationRaw : Number(durationRaw) || 0;

      const ts = row.timestamp ?? row.approved_at ?? row.created_at;
      const timestamp =
        typeof ts === "number"
          ? new Date(ts * 1000).toISOString()
          : typeof ts === "string"
            ? ts
            : new Date().toISOString();

      return {
        id,
        request_id: String(row.request_id ?? row.id ?? ""),
        action_type: String(row.action_type ?? "unknown_action"),
        decided_by: String(row.decided_by ?? row.approved_by ?? "unknown"),
        decision: decisionValue as "approved" | "rejected" | "escalated",
        reason: String(row.reason ?? row.rejection_reason ?? ""),
        duration_seconds: Math.max(0, Math.floor(duration)),
        timestamp,
        requested_by: String(row.requested_by ?? row.requestor_id ?? "unknown"),
      } satisfies HitlDecision;
    })
    .filter((row): row is HitlDecision => row !== null)
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
}

function escapeCsv(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export default function HitlHistoryPage() {
  const [agentFilter, setAgentFilter] = React.useState("");
  const [actionFilter, setActionFilter] = React.useState("");
  const [decisionFilter, setDecisionFilter] = React.useState("all");
  const [dateFrom, setDateFrom] = React.useState("");
  const [dateTo, setDateTo] = React.useState("");

  const historyQuery = useQuery({
    queryKey: ["hitl-history"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/hitl/history", { cache: "no-store" });
      if (!res.ok) throw new Error("HITL history unavailable");
      return normalizeHistory(await res.json());
    },
    refetchInterval: 8_000,
    retry: 0,
  });

  const rows = historyQuery.data ?? [];

  const filtered = rows.filter((row) => {
    const agentOk = !agentFilter.trim() || row.requested_by.toLowerCase().includes(agentFilter.trim().toLowerCase());
    const actionOk = !actionFilter.trim() || row.action_type.toLowerCase().includes(actionFilter.trim().toLowerCase());
    const decisionOk = decisionFilter === "all" || row.decision === decisionFilter;

    const ts = new Date(row.timestamp).getTime();
    const fromOk = !dateFrom || ts >= new Date(`${dateFrom}T00:00:00`).getTime();
    const toOk = !dateTo || ts <= new Date(`${dateTo}T23:59:59`).getTime();

    return agentOk && actionOk && decisionOk && fromOk && toOk;
  });

  const exportCsv = () => {
    const header = ["action", "decided_by", "decision", "reason", "duration_seconds", "timestamp", "requested_by", "request_id"];
    const lines = [
      header.join(","),
      ...filtered.map((row) =>
        [
          row.action_type,
          row.decided_by,
          row.decision,
          row.reason,
          String(row.duration_seconds),
          row.timestamp,
          row.requested_by,
          row.request_id,
        ]
          .map((field) => escapeCsv(field))
          .join(",")
      ),
    ];

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `hitl-history-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(href);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">HITL Decision History</h1>
        <p className="text-sm text-muted-foreground">Operator approval/rejection history by action and timestamp.</p>
      </div>

      <Card className="border border-border bg-card p-4">
        <div className="mb-3 grid gap-3 md:grid-cols-5">
          <Input value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} placeholder="Filter by agent" />
          <Input value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} placeholder="Filter by action" />
          <select
            value={decisionFilter}
            onChange={(e) => setDecisionFilter(e.target.value)}
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="all">All decisions</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="escalated">Escalated</option>
          </select>
          <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>

        <div className="mb-3 flex items-center justify-between">
          <div className="text-xs text-muted-foreground">Rows: {filtered.length}</div>
          <Button size="sm" variant="outline" onClick={exportCsv}>Export CSV</Button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="pb-2">Action</th>
                <th className="pb-2">Decided by</th>
                <th className="pb-2">Decision</th>
                <th className="pb-2">Reason</th>
                <th className="pb-2">Duration</th>
                <th className="pb-2">Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id} className="border-t border-border/70 align-top">
                  <td className="py-2">{row.action_type}</td>
                  <td className="py-2">{row.decided_by}</td>
                  <td className="py-2">
                    <span
                      className={
                        row.decision === "approved"
                          ? "rounded bg-green-500/15 px-2 py-1 text-xs text-green-600"
                          : row.decision === "escalated"
                            ? "rounded bg-yellow-500/15 px-2 py-1 text-xs text-yellow-600"
                            : "rounded bg-red-500/15 px-2 py-1 text-xs text-red-500"
                      }
                    >
                      {row.decision}
                    </span>
                  </td>
                  <td className="py-2 text-muted-foreground">{row.reason || "-"}</td>
                  <td className="py-2">{row.duration_seconds}s</td>
                  <td className="py-2 text-xs">{new Date(row.timestamp).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
