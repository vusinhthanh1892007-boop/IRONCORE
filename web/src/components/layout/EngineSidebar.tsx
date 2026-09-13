"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createMessage, useChatStore } from "@/store/chat-store";
import { cn } from "@/lib/utils";
import {
  Warning as AlertTriangle,
  Database,
  FileText,
  ChatCircle as MessageCircle,
  PushPin as Pin,
  Plus,
  HardDrives as Server,
  Gear as Settings,
  X,
  Check,
} from "@phosphor-icons/react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { LanguageSelector } from "@/components/layout/LanguageSelector";

const SAVED_SCRIPTS = [
  { label: "Deploy Staging", requiresConfirm: false },
  { label: "Clear Cache All", requiresConfirm: true },
];

const MONITORING_LINKS = [
  { label: "Stealth Browser", href: "/stealth" },
  { label: "Bot Channels", href: "/bots" },
  { label: "Plugin & Skills", href: "/plugins" },
  { label: "GraphRAG Memory", href: "/memory" },
];

const MANAGEMENT_LINKS = [
  { label: "Dashboard", href: "/dashboard" },
  { label: "Usage", href: "/dashboard/usage" },
  { label: "Cron Console", href: "/dashboard/cron" },
  { label: "Nodes", href: "/dashboard/nodes" },
  { label: "Logs", href: "/dashboard/logs" },
  { label: "Runtime Config", href: "/dashboard/config" },
  { label: "Alerts", href: "/dashboard/alerts" },
  { label: "HITL Approval", href: "/hitl" },
  { label: "HITL History", href: "/hitl/history" },
  { label: "SIEM", href: "/siem" },
  { label: "IAM", href: "/iam" },
  { label: "AI Catalog", href: "/ai-catalog" },
  { label: "Spatial Map", href: "/spatial" },
  { label: "Forensics", href: "/forensics" },
  { label: "Security Audit", href: "/audit" },
];

export function EngineSidebar() {
  const router = useRouter();
  const { sessions, activeSessionId, switchSession, createSession, togglePinSession } = useChatStore();
  const [confirmScript, setConfirmScript] = React.useState<string | null>(null);

  const pinnedSessions = sessions.filter((s) => s.pinned);
  const recentSessions = sessions.filter((s) => !s.pinned).slice(0, 4);

  const handleNewSession = () => {
    createSession(
      undefined,
      createMessage({
        role: "assistant",
        content:
          "Engine core online. Local workspace ready. Type a command or ask a question to begin.",
        title: "The Engine",
        meta: "Ready",
      })
    );
    router.push("/chat");
  };

  const runScript = (scriptName: string) => {
    // 1. If not in a session, create one first or use active
    if (!activeSessionId) {
      handleNewSession();
    }

    // 2. Dispatch custom event so ChatWindow can catch it and auto-send
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent("engine-run-script", { detail: scriptName }));
    }, 100);

    router.push("/chat");
    setConfirmScript(null);
  };

  const handleScriptClick = (script: { label: string; requiresConfirm: boolean }) => {
    if (script.requiresConfirm) {
      setConfirmScript(script.label);
    } else {
      runScript(script.label);
    }
  };

  return (
    <aside className="hidden min-h-[100dvh] flex-col border-r border-border bg-card px-4 py-5 md:flex">
      <div className="flex items-center gap-2 px-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-900 text-xs font-semibold text-white dark:bg-white dark:text-zinc-900">
          E
        </div>
        <span className="text-sm font-semibold">The Engine</span>
        <ThemeToggle className="ml-auto h-7 w-7" />
      </div>

      <div className="mt-6 space-y-6">
        {/* Pinned sessions */}
        {pinnedSessions.length > 0 && (
          <section className="space-y-2">
            <div className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Pinned
            </div>
            <div className="space-y-1">
              {pinnedSessions.map((session) => (
                <div key={session.id} className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => switchSession(session.id)}
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2 text-sm",
                      session.id === activeSessionId
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/70"
                    )}
                  >
                    <MessageCircle className="h-4 w-4 flex-shrink-0" />
                    <span className="truncate">{session.name}</span>
                  </button>
                  <button
                    type="button"
                    title="Unpin"
                    onClick={() => togglePinSession(session.id)}
                    className="flex-shrink-0 rounded p-1 text-amber-500 opacity-80 hover:opacity-100"
                  >
                    <Pin className="h-3.5 w-3.5 fill-amber-400" />
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="space-y-2">
          <div className="flex items-center justify-between px-2">
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Recent Sessions
            </div>
            <button
              type="button"
              onClick={handleNewSession}
              title="New session"
              className="flex items-center gap-1 rounded-md border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent"
            >
              <Plus className="h-3 w-3" />
              New
            </button>
          </div>
          <div className="space-y-1">
            {sessions.length === 0 && (
              <button
                type="button"
                onClick={handleNewSession}
                className="w-full rounded-lg border border-dashed border-border px-3 py-2 text-left text-xs text-muted-foreground"
              >
                Start a new session
              </button>
            )}
            {recentSessions.map((session) => (
              <div
                key={session.id}
                className={cn(
                  "group flex items-center gap-1 rounded-lg border",
                  session.id === activeSessionId
                    ? "border-zinc-200 bg-zinc-100 text-foreground dark:border-zinc-500 dark:bg-zinc-800 dark:text-zinc-100"
                    : "border-transparent hover:border-zinc-200 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
                )}
              >
                <button
                  type="button"
                  onClick={() => { switchSession(session.id); router.push("/chat"); }}
                  className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-sm dark:text-zinc-100"
                >
                  <MessageCircle className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate">{session.name}</span>
                </button>
                <button
                  type="button"
                  title="Pin session"
                  onClick={() => togglePinSession(session.id)}
                  className="flex-shrink-0 rounded p-1 pr-2 text-muted-foreground/40 opacity-0 transition group-hover:opacity-100 hover:text-foreground dark:text-zinc-400 dark:hover:text-zinc-100"
                >
                  <Pin className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-2">
          <div className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Saved Scripts
          </div>
          <div className="space-y-1">
            {SAVED_SCRIPTS.map((script) => {
              const isConfirming = confirmScript === script.label;
              return (
                <div key={script.label}>
                  {isConfirming ? (
                    /* ── Inline confirmation ── */
                    <div className="rounded-lg border border-amber-500/60 bg-amber-500/10 px-3 py-2 text-xs">
                      <div className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                        <span className="font-medium">Confirm cache clear?</span>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => runScript(script.label)}
                          className="flex items-center gap-1 rounded bg-amber-500 px-2 py-1 text-[10px] font-medium text-white hover:bg-amber-600"
                        >
                          <Check className="h-3 w-3" />
                          Confirm
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmScript(null)}
                          className="flex items-center gap-1 rounded border border-border px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted"
                        >
                          <X className="h-3 w-3" />
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleScriptClick(script)}
                      className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-sm
                        text-muted-foreground hover:bg-accent hover:text-accent-foreground
                        dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100
                        dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
                    >
                      <FileText className="h-4 w-4 shrink-0" />
                      <span className="truncate">{script.label}</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section className="space-y-2">
          <div className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Tools
          </div>
          <div className="space-y-1">
            <Link
              href="/tools?tab=servers"
              className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-sm
                text-muted-foreground hover:bg-zinc-100 hover:text-foreground
                dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100
                dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
            >
              <Server className="h-4 w-4 shrink-0" />
              Servers
            </Link>
            <Link
              href="/tools?tab=databases"
              className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-sm
                text-muted-foreground hover:bg-zinc-100 hover:text-foreground
                dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100
                dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
            >
              <Database className="h-4 w-4 shrink-0" />
              Databases
            </Link>
            <Link
              href="/settings"
              className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-sm
                text-muted-foreground hover:bg-zinc-100 hover:text-foreground
                dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100
                dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
            >
              <Settings className="h-4 w-4 shrink-0" />
              Settings
            </Link>
          </div>
        </section>

        <section className="space-y-2">
          <div className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Monitoring
          </div>
          <div className="space-y-1">
            {MONITORING_LINKS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-sm
                  text-muted-foreground hover:bg-zinc-100 hover:text-foreground
                  dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100
                  dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
              >
                <Server className="h-4 w-4 shrink-0" />
                {item.label}
              </Link>
            ))}
          </div>
        </section>

        <section className="space-y-2">
          <div className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Management
          </div>
          <div className="space-y-1">
            {MANAGEMENT_LINKS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="flex w-full items-center gap-2 rounded-lg border border-transparent px-3 py-2 text-sm
                  text-muted-foreground hover:bg-zinc-100 hover:text-foreground
                  dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100
                  dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
              >
                <Settings className="h-4 w-4 shrink-0" />
                {item.label}
              </Link>
            ))}
          </div>
        </section>
      </div>

      <div className="mt-auto space-y-3 border-t border-border px-2 pt-4">
        <LanguageSelector />
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-xs font-semibold">
            U
          </div>
          <div>
            <div className="text-sm font-semibold">User Name</div>
            <div className="text-xs text-muted-foreground">Admin</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
