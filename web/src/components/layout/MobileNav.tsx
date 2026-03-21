"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { navItems } from "@/components/layout/navigation";
import { useChatStore } from "@/store/chat-store";

interface MobileNavProps {
  variant?: "light" | "dark";
}

export function MobileNav({ variant = "dark" }: MobileNavProps) {
  const pathname = usePathname();
  const sessionCount = useChatStore((state) => state.sessions.length);
  const baseClasses =
    variant === "light"
      ? "border-zinc-200 bg-white/90 text-zinc-600 shadow-[0_-12px_30px_rgba(0,0,0,0.08)]"
      : "border-zinc-800 bg-zinc-950/90 text-zinc-300 shadow-[0_-12px_30px_rgba(0,0,0,0.45)]";
  const activeClasses =
    variant === "light"
      ? "text-zinc-900"
      : "text-white";

  return (
    <nav
      className={cn(
        "fixed bottom-0 left-0 right-0 z-40 md:hidden",
        "border-t backdrop-blur-xl",
        baseClasses
      )}
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-md items-center justify-around px-4 py-3">
        {navItems.map((item) => {
          const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex min-h-[44px] flex-1 flex-col items-center justify-center gap-1 rounded-2xl px-2 py-1 text-[11px] font-medium transition",
                active ? activeClasses : "opacity-70"
              )}
            >
              <Icon className="h-5 w-5" />
              <span className="leading-none">{item.label}</span>
              {item.href === "/chat" && sessionCount > 0 ? (
                <span
                  className={cn(
                    "mt-1 rounded-full px-2 py-0.5 text-[10px]",
                    variant === "light"
                      ? "bg-zinc-900 text-white"
                      : "bg-white text-zinc-900"
                  )}
                >
                  {sessionCount}
                </span>
              ) : null}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
