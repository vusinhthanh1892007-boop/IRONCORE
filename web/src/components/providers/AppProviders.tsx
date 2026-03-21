"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SessionProvider } from "next-auth/react";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { I18nProvider } from "@/components/providers/I18nProvider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      })
  );

  return (
    <ThemeProvider>
      <I18nProvider>
        <SessionProvider>
          <QueryClientProvider client={queryClient}>
            <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
            <Toaster richColors closeButton />
          </QueryClientProvider>
        </SessionProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}
