"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";

type LogLevel = "debug" | "info" | "warn" | "error";

interface LogLine {
  id: string;
  ts: string;
  level: LogLevel;
  sessionId: string;
  agentId: string;
  toolName: string;
  message: string;
}

const levelColor: Record<LogLevel, string> = {
  debug: "text-zinc-400",
  info: "text-blue-400",
  warn: "text-amber-400",
  error: "text-red-400",
};

export default function DashboardLogsPage() {
  const [paused, setPaused] = React.useState(false);
  const [level, setLevel] = React.useState<"all" | LogLevel>("all");
  const [sessionFilter, setSessionFilter] = React.useState("");
  const [agentFilter, setAgentFilter] = React.useState("");
  const [toolFilter, setToolFilter] = React.useState("");
  const [lines] = React.useState<LogLine[]>([]);

  const filtered = lines.filter((line) => {
    if (level !== "all" && line.level !== level) return false;
    if (sessionFilter && !line.sessionId.toLowerCase().includes(sessionFilter.toLowerCase())) return false;
    if (agentFilter && !line.agentId.toLowerCase().includes(agentFilter.toLowerCase())) return false;
    if (toolFilter && !line.toolName.toLowerCase().includes(toolFilter.toLowerCase())) return false;
    return true;
  });

  const exportData = (format: "json" | "csv") => {
    const payload =
      format === "json"
        ? JSON.stringify(filtered, null, 2)
        : ["ts,level,sessionId,agentId,toolName,message", ...filtered.map((l) => `${l.ts},${l.level},${l.sessionId},${l.agentId},${l.toolName},\"${l.message.replace(/\"/g, "'")}\"`)].join("\n");
    const blob = new Blob([payload], { type: format === "json" ? "application/json" : "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `logs-export.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Logs & Debug Center</h1>
        <p className="text-sm text-muted-foreground">Lọc log theo level/session/agent/tool và export JSON/CSV.</p>
      </div>

      <ControlPlaneNav />

      <Card className="border border-border bg-card p-4">
        <div className="grid gap-3 md:grid-cols-6">
          <select className="rounded-lg border border-border bg-background px-2 py-1 text-sm" value={level} onChange={(e) => setLevel(e.target.value as "all" | LogLevel)}>
            <option value="all">all levels</option>
            <option value="debug">debug</option>
            <option value="info">info</option>
            <option value="warn">warn</option>
            <option value="error">error</option>
          </select>
          <Input placeholder="session_id" value={sessionFilter} onChange={(e) => setSessionFilter(e.target.value)} />
          <Input placeholder="agent_id" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} />
          <Input placeholder="tool_name" value={toolFilter} onChange={(e) => setToolFilter(e.target.value)} />
          <Button variant="outline" onClick={() => setPaused((p) => !p)}>{paused ? "Resume stream" : "Pause stream"}</Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => exportData("json")}>Export JSON</Button>
            <Button variant="outline" onClick={() => exportData("csv")}>Export CSV</Button>
          </div>
        </div>
      </Card>

      <Card className="border border-border bg-[#0D1117] p-0">
        <div className="max-h-[560px] overflow-auto p-4 font-mono text-xs">
          {filtered.map((line) => (
            <div key={line.id} className="mb-1 flex gap-3 text-zinc-300">
              <span className="w-20 text-zinc-500">{line.ts}</span>
              <span className={`w-14 font-bold ${levelColor[line.level]}`}>[{line.level}]</span>
              <span className="w-20 text-zinc-400">{line.sessionId}</span>
              <span className="w-24 text-zinc-400">{line.agentId}</span>
              <span className="w-20 text-zinc-400">{line.toolName}</span>
              <span>{line.message}</span>
            </div>
          ))}
          {filtered.length === 0 ? (
            <div className="py-10 text-center text-sm text-zinc-500">
              Live log streaming is not connected yet.
            </div>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
