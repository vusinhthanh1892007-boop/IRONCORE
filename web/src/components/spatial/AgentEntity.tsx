import * as React from "react";
import type { SpatialAgent } from "@/store/spatial-store";

interface AgentEntityProps {
  agent: SpatialAgent;
  x: number;
  y: number;
  active?: boolean;
  onClick?: (agentId: string) => void;
}

const colorByState: Record<SpatialAgent["state"], string> = {
  thinking: "#3b82f6",
  running: "#22c55e",
  waiting: "#eab308",
  error: "#ef4444",
  done: "#6b7280",
};

export function AgentEntity({ agent, x, y, active, onClick }: AgentEntityProps) {
  const color = colorByState[agent.state];
  const letter = agent.shortName.slice(0, 1).toUpperCase();

  return (
    <g
      transform={`translate(${x} ${y})`}
      style={{ transition: "transform 360ms ease" }}
      className="cursor-pointer"
      onClick={() => onClick?.(agent.agentId)}
      role="button"
      aria-label={`Agent ${agent.shortName}`}
    >
      {active ? <circle r={27} fill={color} opacity={0.22} className="animate-pulse" /> : null}
      <circle r={18} fill={color} stroke={active ? "#ffffff" : "#0f172a"} strokeWidth={active ? 2.5 : 1.2} />
      <text textAnchor="middle" dominantBaseline="central" fill="#ffffff" fontSize={12} fontWeight={700}>
        {letter}
      </text>
      <text textAnchor="middle" y={34} fill="#94a3b8" fontSize={11}>
        {agent.shortName}
      </text>
    </g>
  );
}
