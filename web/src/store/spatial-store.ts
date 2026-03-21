import { create } from "zustand";

export type SpatialZone = "planner" | "tool" | "memory" | "hitl" | "incident";
export type SpatialAgentState = "thinking" | "running" | "waiting" | "error" | "done";
export type SpatialEventType = "start" | "tool_call" | "tool_done" | "hitl_wait" | "complete" | "error";

export interface RuntimeAgentEvent {
  id: string;
  agent_id: string;
  event_type: SpatialEventType;
  tool_name?: string;
  session_id: string;
  cost_usd?: number;
  latency_ms?: number;
  severity?: "info" | "low" | "medium" | "high" | "critical";
  timestamp: string;
}

export interface SpatialAgent {
  agentId: string;
  shortName: string;
  sessionId: string;
  zone: SpatialZone;
  state: SpatialAgentState;
  lastEventType: SpatialEventType;
  toolName?: string;
  costUsd: number;
  latencyMs?: number;
  updatedAt: string;
}

interface SpatialState {
  agents: Record<string, SpatialAgent>;
  events: RuntimeAgentEvent[];
  highlightedAgentId: string | null;
  ingestEvent: (event: RuntimeAgentEvent) => void;
  highlightAgent: (agentId: string | null) => void;
  clearLive: () => void;
}

const zoneByEventType: Record<SpatialEventType, SpatialZone> = {
  start: "planner",
  tool_call: "tool",
  tool_done: "memory",
  hitl_wait: "hitl",
  complete: "memory",
  error: "incident",
};

const stateByEventType: Record<SpatialEventType, SpatialAgentState> = {
  start: "thinking",
  tool_call: "running",
  tool_done: "thinking",
  hitl_wait: "waiting",
  complete: "done",
  error: "error",
};

const shortName = (agentId: string) => {
  const token = agentId.split(/[\-_:]/).filter(Boolean).pop() ?? agentId;
  return token.slice(0, 8);
};

export const useSpatialStore = create<SpatialState>((set) => ({
  agents: {},
  events: [],
  highlightedAgentId: null,

  ingestEvent: (event) =>
    set((state) => {
      const previous = state.agents[event.agent_id];
      const next: SpatialAgent = {
        agentId: event.agent_id,
        shortName: shortName(event.agent_id),
        sessionId: event.session_id,
        zone: zoneByEventType[event.event_type],
        state: stateByEventType[event.event_type],
        lastEventType: event.event_type,
        toolName: event.tool_name,
        costUsd: Math.max(0, (previous?.costUsd ?? 0) + (event.cost_usd ?? 0)),
        latencyMs: event.latency_ms,
        updatedAt: event.timestamp,
      };

      return {
        agents: {
          ...state.agents,
          [event.agent_id]: next,
        },
        events: [event, ...state.events].slice(0, 600),
      };
    }),

  highlightAgent: (agentId) => set({ highlightedAgentId: agentId }),

  clearLive: () =>
    set({
      agents: {},
      events: [],
      highlightedAgentId: null,
    }),
}));
