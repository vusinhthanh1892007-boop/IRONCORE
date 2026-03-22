import type { ReactNode } from "react";
import { LinearSidebar } from "@/components/layout/LinearSidebar";
import { MobileNav } from "@/components/layout/MobileNav";
import { CommandPalette } from "@/components/layout/CommandPalette";

export function LinearLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[100dvh] bg-background text-foreground">
      <div className="grid min-h-[100dvh] grid-cols-1 md:grid-cols-[240px_1fr]">
        <LinearSidebar />
        <main className="min-h-[100dvh] bg-background md:border-l md:border-border">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-8 pb-24 md:px-8 md:pb-8">
            {children}
          </div>
        </main>
      </div>
      <MobileNav variant="dark" />
      <CommandPalette />
    </div>
  );
}
