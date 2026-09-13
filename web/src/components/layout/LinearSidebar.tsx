"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Pulse,
  BookOpen,
  Robot as Bot,
  Brain,
  ClockCounterClockwise as FolderClock,
  SquaresFour as LayoutGrid,
  ShieldWarning,
  Plug,
  Detective as Radar,
  GearSix,
  Clock,
  HardDrives,
  Scroll,
  Sliders,
  Warning,
  HandPalm,
  Archive,
  Shield,
  UsersThree,
  Graph,
} from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ui/theme-toggle";

const groups = [
  {
    label: "Core",
    items: [
      { label: "The Engine", href: "/chat", icon: Pulse },
      { label: "Sessions", href: "/sessions", icon: FolderClock },
    ],
  },
  {
    label: "Monitoring",
    items: [
      { label: "Stealth Browser", href: "/stealth", icon: Radar },
      { label: "Bot Channels", href: "/bots", icon: Bot },
      { label: "Plugin & Skills", href: "/plugins", icon: Plug },
      { label: "GraphRAG Memory", href: "/memory", icon: Brain },
    ],
  },
  {
    label: "Management",
    items: [
      { label: "Dashboard", href: "/dashboard", icon: LayoutGrid },
      { label: "Usage", href: "/dashboard/usage", icon: Pulse },
      { label: "Cron Console", href: "/dashboard/cron", icon: Clock },
      { label: "Nodes", href: "/dashboard/nodes", icon: HardDrives },
      { label: "Logs", href: "/dashboard/logs", icon: Scroll },
      { label: "Runtime Config", href: "/dashboard/config", icon: Sliders },
      { label: "Alerts", href: "/dashboard/alerts", icon: Warning },
      { label: "HITL Approval", href: "/hitl", icon: HandPalm },
      { label: "HITL History", href: "/hitl/history", icon: Archive },
      { label: "SIEM", href: "/siem", icon: Shield },
      { label: "IAM", href: "/iam", icon: UsersThree },
      { label: "AI Catalog", href: "/ai-catalog", icon: Brain },
      { label: "Spatial Map", href: "/spatial", icon: Graph },
      { label: "Forensics", href: "/forensics", icon: Scroll },
      { label: "Security Audit", href: "/audit", icon: ShieldWarning },
      { label: "Settings", href: "/settings", icon: GearSix },
    ],
  },
];

export function LinearSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden min-h-[100dvh] flex-col border-r border-border bg-card px-4 py-6 text-card-foreground md:flex">
      <div className="flex items-center gap-3 px-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-xs font-semibold">
          IC
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold">IronCore</span>
          <span className="text-xs text-muted-foreground">Workspace</span>
        </div>
        <ThemeToggle className="ml-auto h-7 w-7" />
      </div>

      <nav className="mt-8 flex flex-1 flex-col gap-6">
        {groups.map((group) => (
          <div key={group.label} className="space-y-2">
            <div className="px-2 text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
              {group.label}
            </div>
            <div className="space-y-1">
              {group.items.map((item) => {
                const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.label}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150",
                      active
                        ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 font-medium"
                        : "text-muted-foreground hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-foreground"
                    )}
                  >
                    <Icon className="h-4 w-4" strokeWidth={1.5} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="mt-auto space-y-2">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
          <BookOpen className="h-4 w-4" strokeWidth={1.5} />
          Operator manual
        </div>
      </div>
    </aside>
  );
}
