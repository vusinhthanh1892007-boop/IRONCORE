"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { ironCoreClient } from "@/lib/api-client";
import { MetricCard } from "@/components/dashboard/MetricCard";
import { TokenSavingsCard } from "@/components/dashboard/TokenSavingsCard";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";
import { Pulse, Coins, Cpu, CurrencyDollar as DollarSign, Clock, WarningCircle } from "@phosphor-icons/react";
import { Activity, HardDrive as HardDrives, Terminal } from "lucide-react";
import { usePullToRefresh } from "@/hooks/usePullToRefresh";

const CostChart = dynamic(
  () => import("@/components/dashboard/CostChart").then((mod) => mod.CostChart),
  { ssr: false }
);
const CacheHitGauge = dynamic(
  () => import("@/components/dashboard/CacheHitGauge").then((mod) => mod.CacheHitGauge),
  { ssr: false }
);

const ranges = [
  { label: "1H", value: "1h" },
  { label: "6H", value: "6h" },
  { label: "24H", value: "24h" },
  { label: "7D", value: "7d" },
];

export default function DashboardPage() {
  const [range, setRange] = React.useState("24h");
  const { data: session } = useSession();

  React.useEffect(() => {
    if (session?.apiKey) {
      ironCoreClient.setApiKey(session.apiKey);
    }
  }, [session?.apiKey]);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["metrics", range],
    queryFn: () => ironCoreClient.getMetrics(range),
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const hitlQuery = useQuery({
    queryKey: ["dashboard-hitl-pending"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/hitl/pending", { cache: "no-store" });
      if (!res.ok) throw new Error("HITL pending unavailable");
      const rows = (await res.json()) as Array<unknown>;
      return rows.length;
    },
    refetchInterval: 15_000,
    retry: 0,
  });

  const nodesQuery = useQuery({
    queryKey: ["dashboard-active-agents"],
    queryFn: async () => {
      const res = await fetch("/api/mesh/nodes", { cache: "no-store" });
      if (!res.ok) throw new Error("nodes unavailable");
      const rows = (await res.json()) as Array<{ active_sessions?: number }>;
      return {
        activeAgents: rows.reduce((sum, n) => sum + (n.active_sessions ?? 0), 0),
        totalNodes: rows.length,
      };
    },
    refetchInterval: 15_000,
    retry: 0,
  });

  const jobsQuery = useQuery({
    queryKey: ["dashboard-jobs"],
    queryFn: async () => {
      const res = await fetch("/api/scheduler/jobs", { cache: "no-store" });
      if (!res.ok) throw new Error("jobs unavailable");
      const rows = (await res.json()) as Array<unknown>;
      return rows.length;
    },
    refetchInterval: 30_000,
    retry: 0,
  });

  usePullToRefresh({
    onRefresh: () => refetch(),
  });

  const totalCalls = data?.total_api_calls ?? 0;
  const cacheHitRate = (data?.cache_hit_rate ?? 0) * 100;
  const totalCost = data?.total_cost_usd ?? 0;
  const savingsPct = data?.savings_pct ?? 0;
  const tokensSavedCache = data?.tokens_saved_by_cache ?? 0;
  const tokensSavedCompression = data?.tokens_saved_by_compression ?? 0;
  const pendingHitl = hitlQuery.data ?? 0;
  const activeAgents = nodesQuery.data?.activeAgents ?? 0;
  const totalNodes = nodesQuery.data?.totalNodes ?? 0;
  const schedulerJobs = jobsQuery.data ?? 0;
  const apiCallsPerMinute = totalCalls > 0 ? Math.round(totalCalls / 60) : 0;

  return (
    <div className="space-y-6 pb-24 md:pb-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Cost & Performance
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-foreground">
            Unified Control Plane
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Track spend, cache efficiency, and token savings.
          </p>
        </div>
        <Tabs value={range} onValueChange={setRange}>
          <TabsList className="bg-muted">
            {ranges.map((item) => (
              <TabsTrigger key={item.value} value={item.value}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <ControlPlaneNav />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <MetricCard
          title="Active Sessions"
          value={totalCalls}
          icon={Activity}
          trendLabel="running"
          loading={isLoading}
        />
        <MetricCard
          title="API Calls / Min"
          value={apiCallsPerMinute}
          icon={Coins}
          trendLabel="realtime"
          loading={isLoading}
        />
        <MetricCard
          title="Cache Hit Rate"
          value={`${cacheHitRate.toFixed(1)}%`}
          icon={Pulse}
          trendLabel="last 24h"
          loading={isLoading}
        />
        <MetricCard
          title="Total Cost Today"
          value={`$${totalCost.toFixed(2)}`}
          icon={DollarSign}
          trend={savingsPct}
          trendLabel="vs baseline"
          loading={isLoading}
        />
        <MetricCard
          title="Active Agents"
          value={activeAgents}
          icon={Cpu}
          trendLabel="mesh workers"
          loading={false}
        />
        <Card className="border border-border bg-card p-5 text-card-foreground">
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Pending HITL Approvals</div>
            <span className={`rounded-full px-2 py-0.5 text-xs ${pendingHitl > 0 ? "bg-red-500/15 text-red-500" : "bg-muted text-muted-foreground"}`}>
              {pendingHitl > 0 ? "Attention" : "Normal"}
            </span>
          </div>
          <div className="mt-3 text-2xl font-semibold">{pendingHitl}</div>
          <div className="mt-2 text-xs text-muted-foreground">Red badge appears when the queue has pending approvals</div>
        </Card>
      </div>

      <TokenSavingsCard
        cacheSaved={tokensSavedCache}
        compressionSaved={tokensSavedCompression}
      />

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Card className="border border-border bg-card p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold">Cost Over Time</div>
              <div className="text-xs text-muted-foreground">With vs without optimizer</div>
            </div>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="mt-4">
            <CostChart data={data?.time_series ?? []} savingsPct={savingsPct} />
          </div>
        </Card>

        <Card className="border border-border bg-card p-5">
          <CacheHitGauge value={cacheHitRate} />
        </Card>
      </div>

      <Card className="border border-border bg-card p-5">
        <div className="text-sm font-semibold">Top Sessions</div>
        <div className="mt-4 space-y-3 text-sm text-muted-foreground">
          {data?.top_sessions?.length ? (
            data.top_sessions.map((session) => (
              <div key={session.session_id} className="flex items-center justify-between">
                <div className="truncate">{session.session_id}</div>
                <div className="font-medium text-foreground">${session.cost_usd.toFixed(3)}</div>
              </div>
            ))
          ) : (
            <div>No session cost data available yet.</div>
          )}
        </div>
      </Card>

      {/* Fleet Telemetry & Control Plane Extensions */}
      <div className="pt-6 border-t border-border mt-8">
        <h2 className="text-xl font-semibold text-foreground mb-4">Fleet Telemetry & Operations</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 mb-6">
          <MetricCard title="Active Instances" value={activeAgents} icon={Activity} trendLabel="Online" loading={nodesQuery.isLoading} />
          <MetricCard title="Total Nodes" value={totalNodes} icon={HardDrives} trendLabel="Connected" loading={nodesQuery.isLoading} />
          <MetricCard title="Pending HITL" value={pendingHitl} icon={WarningCircle} trendLabel="Queue" loading={hitlQuery.isLoading} />
          <MetricCard title="Scheduler Jobs" value={schedulerJobs} icon={Clock} trendLabel="Configured" loading={jobsQuery.isLoading} />
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
          <Card className="border border-border bg-card p-5">
            <h3 className="font-semibold text-sm mb-4 flex justify-between items-center">
              Cron Jobs & Tasks
              <Clock className="h-4 w-4 text-muted-foreground" />
            </h3>
            <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
              {schedulerJobs > 0
                ? `${schedulerJobs} scheduler job(s) available. Open Scheduler Console for full control.`
                : "No scheduler jobs are being reported right now."}
            </div>
          </Card>

          <Card className="border border-border bg-[#0D1117] shadow-sm overflow-hidden flex flex-col p-0">
            <div className="bg-[#161B22] border-b border-border/50 p-3 flex items-center gap-2">
              <Terminal className="h-4 w-4 text-muted-foreground" />
              <span className="text-xs font-mono text-muted-foreground tracking-wider">ironcore-fleet-tail.log</span>
            </div>
            <div className="p-4 font-mono text-xs leading-relaxed flex-1 overflow-y-auto">
              <div className="py-8 text-center text-sm text-zinc-500">
                Live fleet log tail is not connected yet.
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
