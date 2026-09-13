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

interface ServerItem {
  name: string;
  url: string;
  status: "online" | "offline";
}

interface DatabaseItem {
  name: string;
  type: string;
  host: string;
  status: "connected" | "disconnected";
}

function ServersTab() {
  const [servers, setServers] = React.useState<ServerItem[]>([]);
  const [showAdd, setShowAdd] = React.useState(false);
  const [newServer, setNewServer] = React.useState({ name: "", url: "" });

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newServer.name || !newServer.url) return;
    setServers((prev) => [
      ...prev,
      { name: newServer.name, url: newServer.url, status: "online" },
    ]);
    setNewServer({ name: "", url: "" });
    setShowAdd(false);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Connect Model Context Protocol (MCP) servers or API endpoints.
        </p>
        <button
          type="button"
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium
            hover:bg-accent dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          <Plus className="h-3.5 w-3.5" />
          {showAdd ? "Cancel" : "Add Server"}
        </button>
      </div>

      {showAdd ? (
        <form onSubmit={handleAdd} className="rounded-xl border border-border bg-card p-4 space-y-3">
          <div className="text-sm font-semibold">Add MCP Server</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="Server Name (e.g. Local MCP Tools)"
              value={newServer.name}
              onChange={(e) => setNewServer({ ...newServer, name: e.target.value })}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <input
              type="text"
              placeholder="Server URL (e.g. http://localhost:9000)"
              value={newServer.url}
              onChange={(e) => setNewServer({ ...newServer, url: e.target.value })}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <button
            type="submit"
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            Save Server
          </button>
        </form>
      ) : null}

      {servers.length ? (
        <div className="space-y-2">
          {servers.map((s) => (
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
      ) : (
        <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
          No external MCP servers connected yet. Click <strong className="text-foreground">Add Server</strong> to connect an endpoint.
        </div>
      )}
    </div>
  );
}

/* ── Databases Tab ───────────────────────────────────────────────── */

function DatabasesTab() {
  const [databases, setDatabases] = React.useState<DatabaseItem[]>([]);
  const [showAdd, setShowAdd] = React.useState(false);
  const [newDb, setNewDb] = React.useState({ name: "", type: "PostgreSQL", host: "" });

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDb.name || !newDb.host) return;
    setDatabases((prev) => [
      ...prev,
      { name: newDb.name, type: newDb.type, host: newDb.host, status: "connected" },
    ]);
    setNewDb({ name: "", type: "PostgreSQL", host: "" });
    setShowAdd(false);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Connect databases so AI can query directly.
        </p>
        <button
          type="button"
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium
            hover:bg-accent dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
        >
          <Plus className="h-3.5 w-3.5" />
          {showAdd ? "Cancel" : "Add Database"}
        </button>
      </div>

      {showAdd ? (
        <form onSubmit={handleAdd} className="rounded-xl border border-border bg-card p-4 space-y-3">
          <div className="text-sm font-semibold">Connect Database</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              type="text"
              placeholder="Name (e.g. Analytics DB)"
              value={newDb.name}
              onChange={(e) => setNewDb({ ...newDb, name: e.target.value })}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <select
              value={newDb.type}
              onChange={(e) => setNewDb({ ...newDb, type: e.target.value })}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="PostgreSQL">PostgreSQL</option>
              <option value="MySQL">MySQL</option>
              <option value="SQLite">SQLite</option>
              <option value="Redis">Redis</option>
              <option value="MongoDB">MongoDB</option>
            </select>
            <input
              type="text"
              placeholder="Host / URI (e.g. localhost:5432)"
              value={newDb.host}
              onChange={(e) => setNewDb({ ...newDb, host: e.target.value })}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <button
            type="submit"
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            Save Database
          </button>
        </form>
      ) : null}

      {databases.length ? (
        <div className="space-y-2">
          {databases.map((db) => (
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
      ) : (
        <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
          No external databases connected yet. Click <strong className="text-foreground">Add Database</strong> to configure PostgreSQL, MySQL, Redis, or SQLite.
        </div>
      )}
    </div>
  );
}

