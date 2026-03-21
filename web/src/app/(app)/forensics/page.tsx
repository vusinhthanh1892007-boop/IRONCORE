"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ReplayControls } from "@/components/spatial/ReplayControls";
import { AgentEntity } from "@/components/spatial/AgentEntity";
import { EvidenceExport } from "@/components/forensics/EvidenceExport";

interface ForensicsSession {
  session_id: string;
  started_at?: number | string;
  ended_at?: number | string | null;
  event_count?: number;
  primary_agent?: string;
}

interface ForensicsTimelineEvent {
  seq: number;
  event_id: string;
  event_type: string;
  timestamp: number | string;
  metadata: Record<string, unknown>;
  chain_hash_prefix: string;
}

type SpatialZone = "planner" | "tool" | "memory" | "hitl" | "incident";
type SpatialState = "thinking" | "running" | "waiting" | "error" | "done";

const ZONES = [
  { id: "planner", label: "🧠 Planner", x: 24, y: 24, width: 300, height: 170 },
  { id: "tool", label: "🔧 Tool Zone", x: 348, y: 24, width: 300, height: 170 },
  { id: "memory", label: "💾 Memory", x: 672, y: 24, width: 300, height: 170 },
  { id: "hitl", label: "✋ HITL Gate", x: 186, y: 220, width: 300, height: 170 },
  { id: "incident", label: "⚠️ Incident", x: 510, y: 220, width: 300, height: 170 },
] as const;

function toMillis(input: number | string | undefined | null): number {
  if (input == null) return Date.now();
  if (typeof input === "number") return input < 1e12 ? input * 1000 : input;
  const numeric = Number(input);
  if (Number.isFinite(numeric)) return numeric < 1e12 ? numeric * 1000 : numeric;
  const parsed = new Date(input).getTime();
  return Number.isFinite(parsed) ? parsed : Date.now();
}

function deriveZone(eventType: string): SpatialZone {
  const key = eventType.toLowerCase();
  if (key.includes("tool") || key.includes("call")) return "tool";
  if (key.includes("memory") || key.includes("retriev") || key.includes("complete") || key.includes("done")) return "memory";
  if (key.includes("hitl") || key.includes("approval") || key.includes("wait")) return "hitl";
  if (key.includes("error") || key.includes("incident") || key.includes("deny")) return "incident";
  return "planner";
}

function deriveState(eventType: string): SpatialState {
  const key = eventType.toLowerCase();
  if (key.includes("error") || key.includes("incident") || key.includes("deny")) return "error";
  if (key.includes("wait") || key.includes("hitl") || key.includes("approval")) return "waiting";
  if (key.includes("tool") || key.includes("call")) return "running";
  if (key.includes("complete") || key.includes("done") || key.includes("finish")) return "done";
  return "thinking";
}

function shortName(agentId: string) {
  return agentId.split(/[\-_:]/).filter(Boolean).pop()?.slice(0, 8) ?? agentId.slice(0, 8);
}

function safeString(value: unknown, fallback = "unknown") {
  if (typeof value === "string" && value.trim()) return value;
  return fallback;
}

export default function ForensicsPage() {
  const [query, setQuery] = React.useState("");
  const [fromDate, setFromDate] = React.useState("");
  const [toDate, setToDate] = React.useState("");
  const [selectedSessionId, setSelectedSessionId] = React.useState("");
  const [selectedSeq, setSelectedSeq] = React.useState<number | null>(null);
  const [paused, setPaused] = React.useState(true);
  const [speed, setSpeed] = React.useState(1);
  const [cursor, setCursor] = React.useState(0);
  const [focusedAgentId, setFocusedAgentId] = React.useState<string>("");

  const sessionsQuery = useQuery({
    queryKey: ["forensics-sessions"],
    queryFn: async () => {
      const res = await fetch("/api/forensics/sessions", { cache: "no-store" });
      if (!res.ok) throw new Error("Unable to load forensics sessions");
      return (await res.json()) as ForensicsSession[];
    },
    refetchInterval: 15000,
    retry: 0,
  });

  React.useEffect(() => {
    if (selectedSessionId) return;
    const first = sessionsQuery.data?.[0]?.session_id;
    if (first) setSelectedSessionId(first);
  }, [selectedSessionId, sessionsQuery.data]);

  const timelineQuery = useQuery({
    queryKey: ["forensics-timeline", selectedSessionId],
    enabled: !!selectedSessionId,
    queryFn: async () => {
      const res = await fetch(`/api/forensics/sessions/${encodeURIComponent(selectedSessionId)}/timeline?limit=400`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error("Unable to load timeline");
      return (await res.json()) as ForensicsTimelineEvent[];
    },
    retry: 0,
  });

  const verifyQuery = useQuery({
    queryKey: ["forensics-verify", selectedSessionId],
    enabled: !!selectedSessionId,
    queryFn: async () => {
      const res = await fetch(`/api/forensics/sessions/${encodeURIComponent(selectedSessionId)}/verify`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error("Unable to verify chain");
      return (await res.json()) as Record<string, unknown>;
    },
    retry: 0,
  });

  const sessionMap = React.useMemo(() => {
    const map = new Map<string, ForensicsSession>();
    (sessionsQuery.data ?? []).forEach((item) => map.set(item.session_id, item));
    return map;
  }, [sessionsQuery.data]);

  const filteredSessions = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    const from = fromDate ? new Date(fromDate).getTime() : Number.NEGATIVE_INFINITY;
    const to = toDate ? new Date(toDate).getTime() + 24 * 60 * 60 * 1000 - 1 : Number.POSITIVE_INFINITY;

    return (sessionsQuery.data ?? []).filter((session) => {
      const ts = toMillis(session.started_at);
      const matchQuery =
        !q ||
        session.session_id.toLowerCase().includes(q) ||
        safeString(session.primary_agent, "").toLowerCase().includes(q);
      const matchDate = ts >= from && ts <= to;
      return matchQuery && matchDate;
    });
  }, [sessionsQuery.data, query, fromDate, toDate]);

  const timelineOrdered = React.useMemo(() => {
    const rows = timelineQuery.data ?? [];
    return [...rows].sort((a, b) => {
      if (a.seq !== b.seq) return a.seq - b.seq;
      return toMillis(a.timestamp) - toMillis(b.timestamp);
    });
  }, [timelineQuery.data]);

  React.useEffect(() => {
    if (!timelineOrdered.length) {
      setCursor(0);
      setSelectedSeq(null);
      return;
    }
    setCursor((prev) => Math.min(prev, timelineOrdered.length - 1));
    if (selectedSeq == null) {
      setSelectedSeq(timelineOrdered[0].seq);
    }
  }, [timelineOrdered, selectedSeq]);

  React.useEffect(() => {
    if (paused || timelineOrdered.length === 0) return;
    const tickMs = Math.max(120, Math.floor(900 / speed));
    const timer = window.setInterval(() => {
      setCursor((prev) => {
        const next = prev + 1;
        if (next >= timelineOrdered.length) {
          setPaused(true);
          return timelineOrdered.length - 1;
        }
        const targetSeq = timelineOrdered[next]?.seq ?? null;
        setSelectedSeq(targetSeq);
        return next;
      });
    }, tickMs);
    return () => window.clearInterval(timer);
  }, [paused, speed, timelineOrdered]);

  const effectiveIndex = React.useMemo(() => {
    if (!timelineOrdered.length) return 0;
    if (selectedSeq != null) {
      const idx = timelineOrdered.findIndex((event) => event.seq === selectedSeq);
      if (idx >= 0) return idx;
    }
    return Math.min(cursor, timelineOrdered.length - 1);
  }, [timelineOrdered, selectedSeq, cursor]);

  const replayEvents = React.useMemo(
    () => timelineOrdered.slice(0, Math.max(0, effectiveIndex + 1)),
    [timelineOrdered, effectiveIndex]
  );

  const currentEvent = timelineOrdered[effectiveIndex] ?? null;

  const replayAgents = React.useMemo(() => {
    const agents: Record<
      string,
      {
        agentId: string;
        shortName: string;
        zone: SpatialZone;
        state: SpatialState;
        sessionId: string;
        toolName?: string;
        costUsd: number;
        latencyMs?: number;
        updatedAt: string;
      }
    > = {};

    replayEvents.forEach((event) => {
      const metadata = event.metadata ?? {};
      const agentId = safeString(metadata.agent_id, safeString(metadata.requested_by, "agent-unknown"));
      const existing = agents[agentId];
      const zone = deriveZone(event.event_type);
      const state = deriveState(event.event_type);
      const cost = typeof metadata.cost_usd === "number" ? metadata.cost_usd : 0;

      agents[agentId] = {
        agentId,
        shortName: shortName(agentId),
        zone,
        state,
        sessionId: selectedSessionId || safeString(metadata.session_id, "session-unknown"),
        toolName: typeof metadata.tool_name === "string" ? metadata.tool_name : existing?.toolName,
        costUsd: Math.max(0, (existing?.costUsd ?? 0) + cost),
        latencyMs: typeof metadata.latency_ms === "number" ? metadata.latency_ms : existing?.latencyMs,
        updatedAt: new Date(toMillis(event.timestamp)).toISOString(),
      };
    });

    return agents;
  }, [replayEvents, selectedSessionId]);

  const orderedAgents = React.useMemo(
    () => Object.values(replayAgents).sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1)),
    [replayAgents]
  );

  const zoneCounts = orderedAgents.reduce<Record<string, number>>((acc, agent) => {
    acc[agent.zone] = (acc[agent.zone] ?? 0) + 1;
    return acc;
  }, {});

  const positionFor = (zone: SpatialZone, index: number) => {
    const area = ZONES.find((item) => item.id === zone) ?? ZONES[0];
    const cols = 4;
    const row = Math.floor(index / cols);
    const col = index % cols;
    return {
      x: area.x + 52 + col * 64,
      y: area.y + 58 + row * 64,
    };
  };

  const loadSession = React.useCallback(
    (sessionId: string) => {
      if (!sessionId) return;
      setSelectedSessionId(sessionId);
      setPaused(true);
      setCursor(0);
      setSelectedSeq(null);
      setFocusedAgentId("");
    },
    []
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Forensics & Evidence Replay</h1>
        <p className="text-sm text-muted-foreground">
          Phát lại timeline session, đồng bộ spatial map và xuất bằng chứng kiểm toán.
        </p>
      </div>

      <Card className="border border-border bg-card p-3">
        <div className="grid gap-2 md:grid-cols-[1fr_180px_180px_220px]">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by session_id or agent"
          />
          <Input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          <Input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          <select
            value={selectedSessionId}
            onChange={(event) => loadSession(event.target.value)}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">Select session</option>
            {filteredSessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {session.session_id} · {safeString(session.primary_agent, "agent")}
              </option>
            ))}
          </select>
        </div>
      </Card>

      <ReplayControls
        paused={paused}
        speed={speed}
        cursor={effectiveIndex}
        maxCursor={Math.max(0, timelineOrdered.length - 1)}
        onPausedChange={setPaused}
        onSpeedChange={setSpeed}
        onCursorChange={(value) => {
          setCursor(value);
          const seq = timelineOrdered[value]?.seq ?? null;
          setSelectedSeq(seq);
          setPaused(true);
        }}
        onLoadSession={loadSession}
        onExportSnapshot={() => {
          // Export chính thức dùng EvidenceExport bên dưới
        }}
      />

      <div className="grid gap-4 xl:grid-cols-[320px_1fr_360px]">
        <Card className="max-h-[520px] overflow-y-auto border border-border bg-card p-3">
          <div className="mb-2 text-sm font-semibold">Event Timeline</div>
          <div className="space-y-2">
            {timelineOrdered.map((event, index) => {
              const active = index === effectiveIndex;
              const metadata = event.metadata ?? {};
              return (
                <button
                  key={event.event_id}
                  type="button"
                  onClick={() => {
                    setSelectedSeq(event.seq);
                    setCursor(index);
                    setPaused(true);
                    const aid = safeString(metadata.agent_id, "");
                    if (aid) setFocusedAgentId(aid);
                  }}
                  className={`w-full rounded-md border px-3 py-2 text-left ${
                    active ? "border-primary bg-primary/10" : "border-border bg-background/70"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium">#{event.seq} · {event.event_type}</span>
                    <span className="text-muted-foreground">{new Date(toMillis(event.timestamp)).toLocaleTimeString()}</span>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {safeString(metadata.agent_id, "agent-unknown")}
                    {metadata.tool_name ? ` · ${String(metadata.tool_name)}` : ""}
                  </div>
                </button>
              );
            })}
          </div>
        </Card>

        <Card className="overflow-hidden border border-border bg-card p-2">
          <svg viewBox="0 0 1000 410" className="min-h-[410px] w-full rounded-md bg-background">
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
              const pos = positionFor(agent.zone, siblingIndex >= 0 ? siblingIndex : index);

              return (
                <AgentEntity
                  key={agent.agentId}
                  agent={{
                    agentId: agent.agentId,
                    shortName: agent.shortName,
                    sessionId: agent.sessionId,
                    zone: agent.zone,
                    state: agent.state,
                    lastEventType: "start",
                    toolName: agent.toolName,
                    costUsd: agent.costUsd,
                    latencyMs: agent.latencyMs,
                    updatedAt: agent.updatedAt,
                  }}
                  x={pos.x}
                  y={pos.y}
                  active={focusedAgentId === agent.agentId || agent.state === "running"}
                  onClick={setFocusedAgentId}
                />
              );
            })}
          </svg>
        </Card>

        <Card className="space-y-3 border border-border bg-card p-4">
          <div>
            <div className="text-sm font-semibold">Event Details</div>
            {currentEvent ? (
              <div className="mt-2 space-y-2 text-sm">
                <div><strong>Seq:</strong> {currentEvent.seq}</div>
                <div><strong>Event:</strong> {currentEvent.event_type}</div>
                <div><strong>Timestamp:</strong> {new Date(toMillis(currentEvent.timestamp)).toLocaleString()}</div>
                <div><strong>Chain hash:</strong> {currentEvent.chain_hash_prefix}</div>
              </div>
            ) : (
              <div className="mt-2 text-sm text-muted-foreground">No event selected.</div>
            )}
          </div>

          <div>
            <div className="text-sm font-semibold">Metadata / Log</div>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-muted p-2 text-xs">
              {JSON.stringify(currentEvent?.metadata ?? {}, null, 2)}
            </pre>
          </div>

          <div>
            <div className="text-sm font-semibold">Session Verification</div>
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-2 text-xs">
              {JSON.stringify(verifyQuery.data ?? {}, null, 2)}
            </pre>
          </div>
        </Card>
      </div>

      <EvidenceExport
        sessionId={selectedSessionId || "unknown-session"}
        sessionMeta={selectedSessionId ? (sessionMap.get(selectedSessionId) as unknown as Record<string, unknown>) : null}
        verifyMeta={verifyQuery.data ?? null}
        timeline={timelineOrdered as unknown as Array<Record<string, unknown>>}
      />
    </div>
  );
}
