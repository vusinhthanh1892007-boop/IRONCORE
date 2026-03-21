"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Severity = "info" | "low" | "medium" | "high" | "critical";

interface SiemEvent {
  id: string;
  severity: Severity;
  event_type: string;
  source: string;
  cef_line: string;
  timestamp: string;
  details: Record<string, unknown>;
}

const severityClass: Record<Severity, string> = {
  info: "bg-blue-500/15 text-blue-500",
  low: "bg-emerald-500/15 text-emerald-500",
  medium: "bg-yellow-500/15 text-yellow-600",
  high: "bg-orange-500/15 text-orange-500",
  critical: "bg-red-500/15 text-red-500",
};

function normalizeEvent(raw: unknown): SiemEvent | null {
  const row = (raw ?? {}) as Record<string, unknown>;
  const id = String(row.id ?? "");
  if (!id) return null;

  const severityRaw = String(row.severity ?? "info").toLowerCase();
  const severity: Severity =
    severityRaw === "critical" || severityRaw === "high" || severityRaw === "medium" || severityRaw === "low" || severityRaw === "info"
      ? (severityRaw as Severity)
      : "info";

  return {
    id,
    severity,
    event_type: String(row.event_type ?? "unknown_event"),
    source: String(row.source ?? "unknown"),
    cef_line: String(row.cef_line ?? ""),
    timestamp: String(row.timestamp ?? new Date().toISOString()),
    details: row.details && typeof row.details === "object" ? (row.details as Record<string, unknown>) : {},
  };
}

function escapeCsv(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export default function SiemPage() {
  const [severityFilter, setSeverityFilter] = React.useState<"all" | Severity>("all");
  const [search, setSearch] = React.useState("");
  const [paused, setPaused] = React.useState(false);
  const [expandedId, setExpandedId] = React.useState<string>("");
  const [exportCount, setExportCount] = React.useState(100);
  const [streamEvents, setStreamEvents] = React.useState<SiemEvent[]>([]);

  const eventsQuery = useQuery({
    queryKey: ["siem-events"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/siem/events", { cache: "no-store" });
      if (!res.ok) throw new Error("SIEM events unavailable");
      const rows = (await res.json()) as unknown[];
      return rows.map(normalizeEvent).filter((event): event is SiemEvent => event !== null);
    },
    refetchInterval: 12000,
    retry: 0,
  });

  React.useEffect(() => {
    if (paused) return;

    const eventSource = new EventSource("/api/enterprise/siem/stream");

    eventSource.onmessage = (event) => {
      try {
        const parsed = normalizeEvent(JSON.parse(event.data));
        if (!parsed) return;
        setStreamEvents((prev) => [parsed, ...prev].slice(0, 500));
      } catch {
        // ignore malformed lines
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [paused]);

  const baseEvents = eventsQuery.data ?? [];
  const merged = [...streamEvents, ...baseEvents].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  const deduped: SiemEvent[] = [];
  const seen = new Set<string>();
  for (const event of merged) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    deduped.push(event);
  }

  const filtered = deduped.filter((event) => {
    const severityOk = severityFilter === "all" || event.severity === severityFilter;
    const q = search.trim().toLowerCase();
    const searchOk = !q ||
      event.source.toLowerCase().includes(q) ||
      event.event_type.toLowerCase().includes(q) ||
      event.cef_line.toLowerCase().includes(q);
    return severityOk && searchOk;
  });

  const exportEvents = (format: "json" | "csv") => {
    const rows = filtered.slice(0, Math.max(1, exportCount));

    const payload =
      format === "json"
        ? JSON.stringify(rows, null, 2)
        : [
            "id,severity,event_type,source,timestamp,cef_line",
            ...rows.map((event) =>
              [event.id, event.severity, event.event_type, event.source, event.timestamp, event.cef_line]
                .map((field) => escapeCsv(field))
                .join(",")
            ),
          ].join("\n");

    const blob = new Blob([payload], { type: format === "json" ? "application/json" : "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `siem-events-${Date.now()}.${format}`;
    a.click();
    URL.revokeObjectURL(href);
  };

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">SIEM Event Stream</h1>
        <p className="text-sm text-muted-foreground">Theo dõi security events realtime, lọc severity và export JSON/CSV.</p>
      </div>

      <Card className="border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {(["all", "info", "low", "medium", "high", "critical"] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setSeverityFilter(item)}
              className={`rounded-full px-3 py-1 text-xs ${severityFilter === item ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}
            >
              {item.toUpperCase()}
            </button>
          ))}
        </div>

        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto_auto]">
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search source / event_type / text" />
          <Input
            type="number"
            min={1}
            max={5000}
            value={exportCount}
            onChange={(e) => setExportCount(Number(e.target.value) || 100)}
            className="w-28"
          />
          <Button variant="outline" onClick={() => setPaused((v) => !v)}>{paused ? "Resume" : "Pause"}</Button>
          <Button variant="outline" onClick={() => exportEvents("json")}>Export JSON</Button>
          <Button variant="outline" onClick={() => exportEvents("csv")}>Export CSV</Button>
        </div>
      </Card>

      <Card className="border border-border bg-card p-4">
        <div className="mb-3 text-xs text-muted-foreground">Events: {filtered.length}</div>
        <div className="space-y-2">
          {filtered.map((event) => {
            const expanded = expandedId === event.id;
            return (
              <div key={event.id} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${severityClass[event.severity]}`}>{event.severity}</span>
                    <span className="text-sm font-medium">{event.event_type}</span>
                    <span className="text-xs text-muted-foreground">{event.source}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{new Date(event.timestamp).toLocaleString()}</span>
                    <button type="button" className="underline underline-offset-2" onClick={() => setExpandedId(expanded ? "" : event.id)}>
                      {expanded ? "Hide CEF" : "Show CEF"}
                    </button>
                  </div>
                </div>
                {expanded && (
                  <div className="mt-2 space-y-2">
                    <pre className="overflow-auto rounded bg-muted p-2 text-xs">{event.cef_line}</pre>
                    <pre className="overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(event.details, null, 2)}</pre>
                  </div>
                )}
              </div>
            );
          })}
          {filtered.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
              No SIEM events are being reported right now.
            </div>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
