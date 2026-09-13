"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Database, Plus, HardDrives as Server } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "servers", label: "Servers", icon: Server },
  { id: "databases", label: "Databases", icon: Database },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ToolsPage() {
  const params = useSearchParams();
  const [tab, setTab] = React.useState<TabId>(
    (params.get("tab") as TabId) ?? "servers"
  );

  // Sync with URL changes (sidebar link clicks)
  React.useEffect(() => {
    const t = params.get("tab") as TabId;
    if (t && (t === "servers" || t === "databases")) setTab(t);
  }, [params]);

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-1 rounded-xl border border-border bg-card p-1">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
              tab === id
                ? "bg-background text-foreground shadow-sm dark:bg-zinc-800 dark:text-zinc-100"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "servers" && <ServersTab />}
      {tab === "databases" && <DatabasesTab />}
    </div>
  );
}

/* ── Servers Tab ─────────────────────────────────────────────────── */

const DEMO_SERVERS = [
  { name: "MCP Local", url: "http://localhost:9000", status: "online" },
  { name: "API Gateway", url: "https://api.ironcore.local", status: "offline" },
];

function ServersTab() {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Connect Model Context Protocol (MCP) servers or API endpoints.
        </p>
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium
            hover:bg-accent dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Server
        </button>
      </div>

      <div className="space-y-2">
        {DEMO_SERVERS.map((s) => (
          <div
            key={s.name}
            className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3
              dark:border-zinc-700 dark:bg-zinc-900"
          >
            <div className="flex items-center gap-3">
              <Server className="h-5 w-5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium dark:text-zinc-100">{s.name}</div>
                <div className="text-xs text-muted-foreground">{s.url}</div>
              </div>
            </div>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                s.status === "online"
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {s.status === "online" ? "● Online" : "○ Offline"}
            </span>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
        Drag and drop server configuration here, or click{" "}
        <strong className="text-foreground">Add Server</strong> to connect.
      </div>
    </div>
  );
}

/* ── Databases Tab ───────────────────────────────────────────────── */

const DEMO_DATABASES = [
  { name: "PostgreSQL Main", type: "PostgreSQL", host: "localhost:5432", status: "connected" },
  { name: "Redis Cache", type: "Redis", host: "localhost:6379", status: "connected" },
  { name: "MongoDB Dev", type: "MongoDB", host: "localhost:27017", status: "disconnected" },
];

function DatabasesTab() {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Connect databases so AI can query directly.
        </p>
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium
            hover:bg-accent dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Database
        </button>
      </div>

      <div className="space-y-2">
        {DEMO_DATABASES.map((db) => (
          <div
            key={db.name}
            className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3
              dark:border-zinc-700 dark:bg-zinc-900"
          >
            <div className="flex items-center gap-3">
              <Database className="h-5 w-5 text-muted-foreground" />
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium dark:text-zinc-100">{db.name}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {db.type}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground">{db.host}</div>
              </div>
            </div>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium",
                db.status === "connected"
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {db.status === "connected" ? "● Connected" : "○ Disconnected"}
            </span>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
        Supports PostgreSQL, MySQL, MongoDB, Redis, SQLite, and more.
      </div>
    </div>
  );
}

