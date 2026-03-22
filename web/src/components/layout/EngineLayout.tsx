import type { ReactNode } from "react";
import { EngineSidebar } from "@/components/layout/EngineSidebar";
import { MobileNav } from "@/components/layout/MobileNav";

export function EngineLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[100dvh] bg-background text-foreground">
      <div className="grid min-h-[100dvh] grid-cols-1 md:grid-cols-[280px_1fr]">
        <EngineSidebar />
        <main className="min-h-[100dvh] bg-background md:border-l md:border-border">
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-6 pb-24 md:px-10 md:pb-6">
            {children}
          </div>
        </main>
      </div>
      <MobileNav variant="light" />
    </div>
  );
}
