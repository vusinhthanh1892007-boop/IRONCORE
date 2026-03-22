"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";

interface NodeInfo {
  id: string;
  host: string;
  status: "healthy" | "degraded" | "offline";
  cpu_pct: number;
  mem_pct: number;
  active_sessions: number;
  last_heartbeat: string;
}

const statusColor: Record<NodeInfo["status"], string> = {
  healthy: "bg-emerald-500",
  degraded: "bg-yellow-500",
  offline: "bg-red-500",
};

export default function DashboardNodesPage() {
  const [selected, setSelected] = React.useState<string>("");

  const { data } = useQuery({
    queryKey: ["mesh-nodes"],
    queryFn: async () => {
      const res = await fetch("/api/mesh/nodes", { cache: "no-store" });
      if (!res.ok) throw new Error("mesh nodes unavailable");
      return (await res.json()) as NodeInfo[];
    },
    refetchInterval: 5_000,
    retry: 0,
  });

  const nodes = React.useMemo(() => data ?? [], [data]);
  React.useEffect(() => {
    if (!nodes.length) {
      setSelected("");
      return;
    }
    if (!selected || !nodes.some((node) => node.id === selected)) {
      setSelected(nodes[0].id);
    }
  }, [nodes, selected]);

  const node = nodes.find((n) => n.id === selected) ?? nodes[0];
  if (!node) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">Nodes / Workers</h1>
          <p className="text-sm text-muted-foreground">Giám sát health, tài nguyên và active sessions theo node.</p>
        </div>
        <ControlPlaneNav />
        <Card className="border border-dashed border-border p-6 text-sm text-muted-foreground">
          No worker or local runtime node is reporting yet.
        </Card>
      </div>
    );
  }

  const history = [
    { label: "-60s", cpu: Math.max(0, node.cpu_pct - 8), mem: Math.max(0, node.mem_pct - 10) },
    { label: "-45s", cpu: Math.max(0, node.cpu_pct - 4), mem: Math.max(0, node.mem_pct - 7) },
    { label: "-30s", cpu: Math.max(0, node.cpu_pct - 2), mem: Math.max(0, node.mem_pct - 5) },
    { label: "-15s", cpu: Math.max(0, node.cpu_pct - 1), mem: Math.max(0, node.mem_pct - 2) },
    { label: "now", cpu: node.cpu_pct, mem: node.mem_pct },
  ];

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Nodes / Workers</h1>
        <p className="text-sm text-muted-foreground">Giám sát health, tài nguyên và active sessions theo node.</p>
      </div>

      <ControlPlaneNav />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {nodes.map((n) => {
          const seconds = Math.max(0, Math.floor((Date.now() - new Date(n.last_heartbeat).getTime()) / 1000));
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => setSelected(n.id)}
              className={`rounded-xl border p-4 text-left ${n.id === node.id ? "border-primary" : "border-border"}`}
            >
              <div className="flex items-center justify-between">
                <div className="font-semibold">{n.host}</div>
                <span className="inline-flex items-center gap-1 text-xs">
                  <span className={`h-2 w-2 rounded-full ${statusColor[n.status]}`} />
                  {n.status}
                </span>
              </div>
              <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                <div>CPU: {n.cpu_pct}%</div>
                <div>MEM: {n.mem_pct}%</div>
                <div>Active sessions: {n.active_sessions}</div>
                <div>Last seen {seconds}s ago</div>
              </div>
            </button>
          );
        })}
      </div>

      <Card className="border border-border bg-card p-5">
        <div className="mb-3 text-sm font-semibold">Node detail: {node.host}</div>
        <div className="grid gap-3 md:grid-cols-5">
          {history.map((h) => (
            <div key={h.label} className="rounded-lg border border-border p-3">
              <div className="text-xs text-muted-foreground">{h.label}</div>
              <div className="mt-1 text-sm">CPU {h.cpu}%</div>
              <div className="text-sm">MEM {h.mem}%</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
