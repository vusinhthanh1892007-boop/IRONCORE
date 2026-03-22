"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkle as Sparkles } from "@phosphor-icons/react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MobileNav } from "@/components/layout/MobileNav";
import { navItems } from "@/components/layout/navigation";
import { useChatStore } from "@/store/chat-store";
import { ThemeToggle } from "@/components/ui/theme-toggle";

export function TopBar() {
  const pathname = usePathname();
  const sessionCount = useChatStore((state) => state.sessions.length);
  const activeLabel =
    navItems.find((item) => pathname === item.href || pathname?.startsWith(`${item.href}/`))
      ?.label ?? "Console";

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between border-b border-border/60 bg-background/80 px-4 py-3 backdrop-blur md:px-6">
      <div className="flex items-center gap-3">
        <MobileNav />
        <div>
          <div className="text-sm font-semibold tracking-tight">{activeLabel}</div>
          <div className="text-xs text-muted-foreground">
            Secure control plane · streaming ready
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {sessionCount > 0 ? (
          <Badge variant="secondary">{sessionCount} active</Badge>
        ) : null}
        <ThemeToggle />
        <Button asChild variant="outline" size="sm" className="gap-2">
          <Link href="/chat">
            <Sparkles className="h-4 w-4" />
            New session
          </Link>
        </Button>
      </div>
    </header>
  );
}
