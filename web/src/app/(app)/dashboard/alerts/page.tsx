"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";

type Severity = "critical" | "high" | "medium";

interface Incident {
  id: string;
  title: string;
  severity: Severity;
  status: "open" | "resolved";
  source: string;
  suggestedAction: string;
  createdAt: string;
}

const fallbackIncidents: Incident[] = [
  {
    id: "inc-001",
    title: "High error rate on agent-main",
    severity: "high",
    status: "open",
    source: "runtime.monitor",
    suggestedAction: "Scale worker replicas and inspect recent deployment diff.",
    createdAt: new Date().toISOString(),
  },
  {
    id: "inc-002",
    title: "HITL queue nearing SLA timeout",
    severity: "critical",
    status: "open",
    source: "enterprise.hitl",
    suggestedAction: "Assign on-call approver and enable auto-escalation policy.",
    createdAt: new Date(Date.now() - 40 * 60 * 1000).toISOString(),
  },
  {
    id: "inc-003",
    title: "Cache hit rate dropped below threshold",
    severity: "medium",
    status: "open",
    source: "optimizer.cache",
    suggestedAction: "Rebuild semantic cache index and review retrieval filters.",
    createdAt: new Date(Date.now() - 80 * 60 * 1000).toISOString(),
  },
];

const severityClass: Record<Severity, string> = {
  critical: "bg-red-500/15 text-red-500",
  high: "bg-orange-500/15 text-orange-500",
  medium: "bg-yellow-500/15 text-yellow-600",
};

export default function DashboardAlertsPage() {
  const [incidents, setIncidents] = React.useState<Incident[]>(fallbackIncidents);
  const [selectedId, setSelectedId] = React.useState(fallbackIncidents[0].id);

  const selected = incidents.find((i) => i.id === selectedId) ?? incidents[0];

  const resolveIncident = (id: string) => {
    setIncidents((prev) => prev.map((i) => (i.id === id ? { ...i, status: "resolved" } : i)));
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Alert / Incident Panel</h1>
        <p className="text-sm text-muted-foreground">Theo dõi incidents, xem suggested action và đánh dấu resolved.</p>
      </div>

      <ControlPlaneNav />

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card className="border border-border bg-card p-4">
          <div className="mb-3 text-sm font-semibold">Incident list</div>
          <div className="space-y-2">
            {incidents.map((incident) => (
              <button
                key={incident.id}
                type="button"
                onClick={() => setSelectedId(incident.id)}
                className={`w-full rounded-lg border p-3 text-left ${incident.id === selected.id ? "border-primary" : "border-border"}`}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium">{incident.title}</div>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${severityClass[incident.severity]}`}>{incident.severity}</span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{incident.source} · {new Date(incident.createdAt).toLocaleString()}</div>
              </button>
            ))}
          </div>
        </Card>

        <Card className="border border-border bg-card p-4">
          <div className="mb-3 text-sm font-semibold">Incident detail</div>
          <div className="space-y-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground">Title</div>
              <div className="font-medium">{selected.title}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Severity</div>
              <span className={`rounded-full px-2 py-0.5 text-xs ${severityClass[selected.severity]}`}>{selected.severity}</span>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Status</div>
              <div>{selected.status}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Suggested action</div>
              <div>{selected.suggestedAction}</div>
            </div>
            <Button
              onClick={() => resolveIncident(selected.id)}
              disabled={selected.status === "resolved"}
            >
              Mark resolved
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
