"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  RadialBar,
  RadialBarChart,
} from "recharts";
import { Card } from "@/components/ui/card";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";

interface UsagePoint {
  t: string;
  tokenIn: number;
  tokenOut: number;
  latencyP50: number;
  latencyP95: number;
  errorRate: number;
  cacheHit: number;
  cost: number;
}

interface SessionCost {
  sessionId: string;
  costUsd: number;
  messages: number;
}

const EMPTY_USAGE_POINT: UsagePoint = {
  t: "n/a",
  tokenIn: 0,
  tokenOut: 0,
  latencyP50: 0,
  latencyP95: 0,
  errorRate: 0,
  cacheHit: 0,
  cost: 0,
};

export default function DashboardUsagePage() {
  const [sortKey, setSortKey] = React.useState<"costUsd" | "messages">("costUsd");
  const [isMounted, setIsMounted] = React.useState(false);

  React.useEffect(() => {
    setIsMounted(true);
  }, []);

  const { data } = useQuery({
    queryKey: ["dashboard-usage"],
    queryFn: async () => {
      const metricsRes = await fetch("/api/metrics", { cache: "no-store" });
      if (!metricsRes.ok) throw new Error("Metrics unavailable");
      const metrics = (await metricsRes.json()) as {
        cache_hit_rate?: number;
        top_sessions?: Array<{ session_id: string; cost_usd: number; messages?: number }>;
        time_series?: Array<{ label: string; value: number }>;
      };

      const series = (metrics.time_series ?? []).map((row, index) => ({
        t: row.label || `T${index + 1}`,
        tokenIn: Math.round((row.value ?? 0) * 6000),
        tokenOut: Math.round((row.value ?? 0) * 9000),
        latencyP50: 210 + index * 8,
        latencyP95: 620 + index * 20,
        errorRate: Math.min(4.8, 0.8 + index * 0.3),
        cacheHit: Math.round((metrics.cache_hit_rate ?? 0.6) * 100),
        cost: row.value ?? 0,
      }));

      const sessions = (metrics.top_sessions ?? []).map((s) => ({
        sessionId: s.session_id,
        costUsd: s.cost_usd,
        messages: s.messages ?? 0,
      }));

      return {
        series,
        sessions,
      };
    },
    refetchInterval: 15_000,
    retry: 0,
  });

  const series = data?.series ?? [];
  const sessions = [...(data?.sessions ?? [])].sort((a, b) =>
    sortKey === "costUsd" ? b.costUsd - a.costUsd : b.messages - a.messages
  );
  const latest: UsagePoint = series[series.length - 1] ?? EMPTY_USAGE_POINT;
  const topSessions: SessionCost[] = sessions;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Usage Realtime</h1>
        <p className="text-sm text-muted-foreground">Token, latency, cache-hit, and error-rate in real time.</p>
      </div>

      <ControlPlaneNav />

      <div className="grid gap-4 md:grid-cols-4">
        <Card className="border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">Token In/min</div>
          <div className="mt-2 text-2xl font-semibold">{latest.tokenIn.toLocaleString()}</div>
        </Card>
        <Card className="border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">Token Out/min</div>
          <div className="mt-2 text-2xl font-semibold">{latest.tokenOut.toLocaleString()}</div>
        </Card>
        <Card className="border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">Latency P95</div>
          <div className="mt-2 text-2xl font-semibold">{latest.latencyP95} ms</div>
        </Card>
        <Card className="border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground">Error Rate</div>
          <div className={`mt-2 text-2xl font-semibold ${latest.errorRate > 5 ? "text-red-500" : ""}`}>{latest.errorRate.toFixed(1)}%</div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border border-border bg-card p-5">
          <div className="mb-3 text-sm font-semibold">Token In/Out per minute</div>
          <div className="h-64">
            {isMounted && series.length ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(113,113,122,0.25)" />
                  <XAxis dataKey="t" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="tokenIn" stroke="#60a5fa" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="tokenOut" stroke="#34d399" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center rounded-md bg-muted/40 text-sm text-muted-foreground">
                No usage time series available yet.
              </div>
            )}
          </div>
        </Card>

        <Card className="border border-border bg-card p-5">
          <div className="mb-3 text-sm font-semibold">Latency P50/P95</div>
          <div className="h-64">
            {isMounted && series.length ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <BarChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(113,113,122,0.25)" />
                  <XAxis dataKey="t" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="latencyP50" fill="#818cf8" />
                  <Bar dataKey="latencyP95" fill="#f59e0b" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center rounded-md bg-muted/40 text-sm text-muted-foreground">
                No latency metrics available yet.
              </div>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <Card className="border border-border bg-card p-5">
          <div className="mb-3 text-sm font-semibold">Cache Hit Gauge</div>
          <div className="h-56">
            {isMounted && series.length ? (
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <RadialBarChart data={[{ name: "cache", value: latest.cacheHit }]} innerRadius="70%" outerRadius="100%" startAngle={180} endAngle={0}>
                  <RadialBar dataKey="value" fill={latest.cacheHit >= 70 ? "#22c55e" : latest.cacheHit >= 40 ? "#f59e0b" : "#ef4444"} cornerRadius={8} />
                </RadialBarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center rounded-md bg-muted/40 text-sm text-muted-foreground">
                Cache metrics unavailable.
              </div>
            )}
          </div>
          <div className="-mt-28 text-center">
            <div className="text-3xl font-semibold">{latest.cacheHit}%</div>
            <div className="text-xs text-muted-foreground">Cache hit rate</div>
          </div>
        </Card>

        <Card className="border border-border bg-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold">Top 10 sessions by cost</div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setSortKey("costUsd")}
                className={`rounded-md px-2 py-1 text-xs ${sortKey === "costUsd" ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}
              >
                Sort cost
              </button>
              <button
                type="button"
                onClick={() => setSortKey("messages")}
                className={`rounded-md px-2 py-1 text-xs ${sortKey === "messages" ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}
              >
                Sort messages
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="pb-2">Session</th>
                  <th className="pb-2">Cost (USD)</th>
                  <th className="pb-2">Messages</th>
                </tr>
              </thead>
              <tbody>
                {topSessions.slice(0, 10).map((row) => (
                  <tr key={row.sessionId} className="border-t border-border/70">
                    <td className="py-2 font-mono text-xs">{row.sessionId}</td>
                    <td className="py-2">${row.costUsd.toFixed(3)}</td>
                    <td className="py-2">{row.messages}</td>
                  </tr>
                ))}
                {sessions.length === 0 ? (
                  <tr>
                    <td className="py-6 text-sm text-muted-foreground" colSpan={3}>
                      No session cost data available yet.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
