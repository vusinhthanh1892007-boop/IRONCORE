"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { SpatialTimeline } from "@/components/spatial/SpatialTimeline";
import { ReplayControls } from "@/components/spatial/ReplayControls";
import { AgentEntity } from "@/components/spatial/AgentEntity";
import {
  useSpatialStore,
  type RuntimeAgentEvent,
  type SpatialEventType,
  type SpatialAgent,
} from "@/store/spatial-store";

type SpatialSeverity = "info" | "low" | "medium" | "high" | "critical";

const ZONES = [
  { id: "planner", label: "🧠 Planner", x: 24, y: 24, width: 300, height: 180 },
  { id: "tool", label: "🔧 Tool Zone", x: 348, y: 24, width: 300, height: 180 },
  { id: "memory", label: "💾 Memory", x: 672, y: 24, width: 300, height: 180 },
  { id: "hitl", label: "✋ HITL Gate", x: 186, y: 230, width: 300, height: 180 },
  { id: "incident", label: "⚠️ Incident", x: 510, y: 230, width: 300, height: 180 },
] as const;

const fallbackReplayTypes: SpatialEventType[] = [
  "start",
  "tool_call",
  "tool_done",
  "tool_call",
  "hitl_wait",
  "tool_done",
  "complete",
];

function normalizeIncoming(raw: unknown): RuntimeAgentEvent | null {
  const row = (raw ?? {}) as Record<string, unknown>;
  const eventTypeRaw = String(row.event_type ?? "");

  const known: SpatialEventType[] = ["start", "tool_call", "tool_done", "hitl_wait", "complete", "error"];
  const mapped: SpatialEventType = known.includes(eventTypeRaw as SpatialEventType)
    ? (eventTypeRaw as SpatialEventType)
    : eventTypeRaw.includes("tool")
      ? eventTypeRaw.includes("done") || eventTypeRaw.includes("finish")
        ? "tool_done"
        : "tool_call"
      : eventTypeRaw.includes("stop") || eventTypeRaw.includes("complete")
        ? "complete"
        : eventTypeRaw.includes("error")
          ? "error"
          : eventTypeRaw.includes("hitl") || eventTypeRaw.includes("approval")
            ? "hitl_wait"
            : "start";

  const agentId = String(row.agent_id ?? row.session_id ?? row.event_id ?? "agent-unknown");
  const sessionId = String(row.session_id ?? "session-unknown");
  const id = String(row.id ?? row.event_id ?? `${agentId}-${Date.now()}`);

  if (!id) return null;

  const severityRaw = String(row.severity ?? "info").toLowerCase();
  const severity: SpatialSeverity =
    severityRaw === "critical" || severityRaw === "high" || severityRaw === "medium" || severityRaw === "low"
      ? severityRaw
      : "info";

  return {
    id,
    agent_id: agentId,
    event_type: mapped,
    tool_name: row.tool_name ? String(row.tool_name) : undefined,
    session_id: sessionId,
    cost_usd: typeof row.cost_usd === "number" ? row.cost_usd : undefined,
    latency_ms: typeof row.latency_ms === "number" ? row.latency_ms : undefined,
    severity,
    timestamp: String(row.timestamp ?? new Date().toISOString()),
  };
}

function replayAgents(events: RuntimeAgentEvent[]): Record<string, SpatialAgent> {
  const result: Record<string, SpatialAgent> = {};
  for (const event of events) {
    const existing = result[event.agent_id];
    const zone =
      event.event_type === "start"
        ? "planner"
        : event.event_type === "tool_call"
          ? "tool"
          : event.event_type === "tool_done" || event.event_type === "complete"
            ? "memory"
            : event.event_type === "hitl_wait"
              ? "hitl"
              : "incident";

    const state =
      event.event_type === "start"
        ? "thinking"
        : event.event_type === "tool_call"
          ? "running"
          : event.event_type === "hitl_wait"
            ? "waiting"
            : event.event_type === "error"
              ? "error"
              : event.event_type === "complete"
                ? "done"
                : "thinking";

    result[event.agent_id] = {
      agentId: event.agent_id,
      shortName: event.agent_id.split(/[\-_:]/).filter(Boolean).pop()?.slice(0, 8) ?? event.agent_id.slice(0, 8),
      sessionId: event.session_id,
      zone,
      state,
      lastEventType: event.event_type,
      toolName: event.tool_name,
      costUsd: Math.max(0, (existing?.costUsd ?? 0) + (event.cost_usd ?? 0)),
      latencyMs: event.latency_ms,
      updatedAt: event.timestamp,
    };
  }
  return result;
}

function positionFor(zone: SpatialAgent["zone"], index: number) {
  const zoneDef = ZONES.find((item) => item.id === zone) ?? ZONES[0];
  const columns = 4;
  const row = Math.floor(index / columns);
  const col = index % columns;
  return {
    x: zoneDef.x + 52 + col * 66,
    y: zoneDef.y + 62 + row * 68,
  };
}

export default function SpatialPage() {
  const liveAgents = useSpatialStore((state) => state.agents);
  const liveEvents = useSpatialStore((state) => state.events);
  const highlightedAgentId = useSpatialStore((state) => state.highlightedAgentId);
  const ingestEvent = useSpatialStore((state) => state.ingestEvent);
  const highlightAgent = useSpatialStore((state) => state.highlightAgent);

  const [replaySource, setReplaySource] = React.useState<RuntimeAgentEvent[] | null>(null);
  const [paused, setPaused] = React.useState(true);
  const [speed, setSpeed] = React.useState(1);
  const [cursor, setCursor] = React.useState(0);

  React.useEffect(() => {
    const source = new EventSource("/api/runtime/agents/stream");
    source.onmessage = (event) => {
      try {
        const parsed = normalizeIncoming(JSON.parse(event.data));
        if (!parsed) return;
        ingestEvent(parsed);
      } catch {
        // ignore malformed events
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
    };
  }, [ingestEvent]);

  const replayEvents = React.useMemo(() => {
    if (!replaySource) return null;
    return replaySource.slice(0, Math.min(cursor + 1, replaySource.length));
  }, [replaySource, cursor]);

  React.useEffect(() => {
    if (paused || !replaySource?.length) return;
    const tickMs = Math.max(120, Math.floor(850 / speed));
    const timer = window.setInterval(() => {
      setCursor((prev) => {
        const next = prev + 1;
        if (next >= replaySource.length) {
          setPaused(true);
          return replaySource.length - 1;
        }
        return next;
      });
    }, tickMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [paused, replaySource, speed]);

  const agents = replayEvents ? replayAgents(replayEvents) : liveAgents;
  const events = replaySource ? replaySource : liveEvents;
  const displayedEvents = replayEvents ?? events;

  const selectedAgent = highlightedAgentId ? agents[highlightedAgentId] : undefined;

  const orderedAgents = Object.values(agents).sort((a, b) =>
    a.updatedAt < b.updatedAt ? 1 : -1
  );

  const zoneCounts = orderedAgents.reduce<Record<string, number>>((acc, agent) => {
    acc[agent.zone] = (acc[agent.zone] ?? 0) + 1;
    return acc;
  }, {});

  const loadSessionReplay = React.useCallback(
    (sessionId: string) => {
      const fromLive = [...liveEvents]
        .reverse()
        .filter((event) => event.session_id === sessionId)
        .slice(-120);

      if (fromLive.length >= 3) {
        setReplaySource(fromLive);
        setCursor(0);
        setPaused(true);
        return;
      }

      const generated: RuntimeAgentEvent[] = fallbackReplayTypes.map((type, idx) => ({
        id: `${sessionId}-${idx}`,
        agent_id: `agent-${sessionId.slice(0, 6) || "demo"}`,
        event_type: type,
        session_id: sessionId,
        tool_name: type.includes("tool") ? "runtime.exec" : undefined,
        cost_usd: idx % 2 === 0 ? 0.002 + idx * 0.0003 : undefined,
        latency_ms: 180 + idx * 35,
        severity: type === "error" ? "high" : "info",
        timestamp: new Date(Date.now() - (fallbackReplayTypes.length - idx) * 1400).toISOString(),
      }));

      setReplaySource(generated);
      setCursor(0);
      setPaused(true);
    },
    [liveEvents]
  );

  const exportSnapshot = React.useCallback(() => {
    const payload = {
      generated_at: new Date().toISOString(),
      replay_enabled: !!replaySource,
      cursor,
      agents,
      events: displayedEvents,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `spatial-replay-${Date.now()}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [agents, cursor, displayedEvents, replaySource]);

  const maxCursor = replaySource ? Math.max(0, replaySource.length - 1) : Math.max(0, events.length - 1);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Spatial Agent 2D Map</h1>
        <p className="text-sm text-muted-foreground">
          Quan sát runtime theo zone: planner, tool, memory, HITL và incident theo thời gian thực.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <Card className="overflow-hidden border border-border bg-card p-2">
          <div className="w-full overflow-x-auto">
            <svg viewBox="0 0 1000 430" className="min-h-[430px] min-w-[980px] rounded-md bg-background">
              {ZONES.map((zone) => (
                <g key={zone.id}>
                  <rect
                    x={zone.x}
                    y={zone.y}
                    width={zone.width}
                    height={zone.height}
                    rx={14}
                    fill="rgba(148,163,184,0.08)"
                    stroke="rgba(148,163,184,0.28)"
                  />
                  <text x={zone.x + 12} y={zone.y + 20} fill="#94a3b8" fontSize={13}>
                    {zone.label} ({zoneCounts[zone.id] ?? 0})
                  </text>
                </g>
              ))}

              {orderedAgents.map((agent, index) => {
                const siblings = orderedAgents.filter((item) => item.zone === agent.zone);
                const siblingIndex = siblings.findIndex((item) => item.agentId === agent.agentId);
                const { x, y } = positionFor(agent.zone, Math.max(0, siblingIndex >= 0 ? siblingIndex : index));
                return (
                  <AgentEntity
                    key={agent.agentId}
                    agent={agent}
                    x={x}
                    y={y}
                    active={highlightedAgentId === agent.agentId || agent.state === "running"}
                    onClick={highlightAgent}
                  />
                );
              })}
            </svg>
          </div>
        </Card>

        <Card className="border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Agent detail</h2>
          {selectedAgent ? (
            <div className="mt-3 space-y-2 text-sm">
              <div className="rounded-md bg-muted p-2"><strong>Agent:</strong> {selectedAgent.agentId}</div>
              <div><strong>Session:</strong> {selectedAgent.sessionId}</div>
              <div><strong>Zone:</strong> {selectedAgent.zone}</div>
              <div><strong>State:</strong> {selectedAgent.state}</div>
              <div><strong>Last event:</strong> {selectedAgent.lastEventType}</div>
              <div><strong>Tool:</strong> {selectedAgent.toolName ?? "—"}</div>
              <div><strong>Cost:</strong> ${selectedAgent.costUsd.toFixed(4)}</div>
              <div><strong>Latency:</strong> {selectedAgent.latencyMs ? `${selectedAgent.latencyMs} ms` : "—"}</div>
              <div><strong>Updated:</strong> {new Date(selectedAgent.updatedAt).toLocaleString()}</div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">Click một agent trên map để xem chi tiết session/tool/cost/latency.</p>
          )}
        </Card>
      </div>

      <ReplayControls
        paused={paused}
        speed={speed}
        cursor={cursor}
        maxCursor={maxCursor}
        onPausedChange={setPaused}
        onSpeedChange={setSpeed}
        onCursorChange={setCursor}
        onLoadSession={loadSessionReplay}
        onExportSnapshot={exportSnapshot}
      />

      <SpatialTimeline
        events={displayedEvents}
        onSelectEvent={(event) => {
          highlightAgent(event.agent_id);
        }}
      />
    </div>
  );
}
