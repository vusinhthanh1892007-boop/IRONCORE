"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CaretLeft as ChevronLeft, CaretRight as ChevronRight } from "@phosphor-icons/react";
import { navItems } from "@/components/layout/navigation";
import { useChatStore } from "@/store/chat-store";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = React.useState(false);
  const sessionCount = useChatStore((state) => state.sessions.length);

  return (
    <aside
      className={cn(
        "relative hidden min-h-screen border-r border-border/60 bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:flex",
        collapsed ? "w-20" : "w-64"
      )}
      data-collapsed={collapsed}
    >
      <div className="flex h-full w-full flex-col">
        <div className="flex items-center justify-between px-4 py-5">
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-sidebar-primary text-sidebar-primary-foreground">
              IC
            </div>
            <div className={cn("transition-opacity", collapsed && "opacity-0")}>
              <div className="text-sm font-semibold">IronCore V2</div>
              <div className="text-xs text-muted-foreground">UI Console</div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setCollapsed((value) => !value)}
            aria-label="Toggle sidebar"
          >
            {collapsed ? <ChevronRight /> : <ChevronLeft />}
          </Button>
        </div>

        <nav className="flex flex-1 flex-col gap-2 px-3">
          {navItems.map((item) => {
            const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group flex items-center gap-3 rounded-2xl px-3 py-2 text-sm font-medium transition",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
                )}
              >
                <Icon className="h-5 w-5" />
                <span className={cn("transition-opacity", collapsed && "opacity-0")}>{item.label}</span>
                {item.href === "/chat" && sessionCount > 0 ? (
                  <Badge
                    variant="secondary"
                    className={cn("ml-auto", collapsed && "hidden")}
                  >
                    {sessionCount}
                  </Badge>
                ) : null}
              </Link>
            );
          })}
        </nav>

        <div className="px-4 pb-6">
          <div className="rounded-2xl border border-sidebar-border/70 bg-sidebar-accent/50 p-4 text-xs text-sidebar-foreground/80">
            <div className="font-semibold">Realtime status</div>
            <div className={cn("mt-1", collapsed && "hidden")}>
              Optimizer cache, plugins, and sessions stream here.
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
