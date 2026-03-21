"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { RuntimeAgentEvent } from "@/store/spatial-store";

interface SpatialTimelineProps {
  events: RuntimeAgentEvent[];
  onSelectEvent: (event: RuntimeAgentEvent) => void;
}

const severityClass: Record<string, string> = {
  critical: "bg-red-500/20 text-red-500",
  high: "bg-orange-500/20 text-orange-500",
  medium: "bg-yellow-500/20 text-yellow-600",
  low: "bg-emerald-500/20 text-emerald-500",
  info: "bg-blue-500/20 text-blue-500",
};

export function SpatialTimeline({ events, onSelectEvent }: SpatialTimelineProps) {
  const [agentFilter, setAgentFilter] = React.useState("");
  const [typeFilter, setTypeFilter] = React.useState("all");
  const [severityFilter, setSeverityFilter] = React.useState("all");

  const filtered = React.useMemo(() => {
    const query = agentFilter.trim().toLowerCase();
    return events.filter((event) => {
      const matchAgent = !query || event.agent_id.toLowerCase().includes(query);
      const matchType = typeFilter === "all" || event.event_type === typeFilter;
      const severity = event.severity ?? "info";
      const matchSeverity = severityFilter === "all" || severity === severityFilter;
      return matchAgent && matchType && matchSeverity;
    });
  }, [events, agentFilter, typeFilter, severityFilter]);

  return (
    <Card className="border border-border bg-card p-3">
      <div className="mb-3 grid gap-2 md:grid-cols-[1fr_180px_180px]">
        <Input
          value={agentFilter}
          onChange={(event) => setAgentFilter(event.target.value)}
          placeholder="Filter by agent"
        />
        <select
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
        >
          <option value="all">All event types</option>
          <option value="start">start</option>
          <option value="tool_call">tool_call</option>
          <option value="tool_done">tool_done</option>
          <option value="hitl_wait">hitl_wait</option>
          <option value="complete">complete</option>
          <option value="error">error</option>
        </select>
        <select
          value={severityFilter}
          onChange={(event) => setSeverityFilter(event.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
        >
          <option value="all">All severities</option>
          <option value="info">info</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="critical">critical</option>
        </select>
      </div>

      <div className="max-h-52 space-y-2 overflow-y-auto pr-1">
        {filtered.map((event) => (
          <button
            key={event.id}
            type="button"
            onClick={() => onSelectEvent(event)}
            className="flex w-full items-center justify-between rounded-md border border-border bg-background/70 px-3 py-2 text-left text-xs hover:bg-muted"
          >
            <div className="space-y-1">
              <div className="font-medium text-foreground">{event.agent_id}</div>
              <div className="text-muted-foreground">
                {event.event_type}
                {event.tool_name ? ` · ${event.tool_name}` : ""}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded-full px-2 py-0.5 ${severityClass[event.severity ?? "info"]}`}>
                {event.severity ?? "info"}
              </span>
              <span className="text-muted-foreground">{new Date(event.timestamp).toLocaleTimeString()}</span>
            </div>
          </button>
        ))}
      </div>
    </Card>
  );
}
