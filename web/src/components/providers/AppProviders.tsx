"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SessionProvider } from "next-auth/react";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { I18nProvider } from "@/components/providers/I18nProvider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  React.useEffect(() => {
    const cacheVersion = "en-only-web-v2";
    const cacheKey = "ironcore_web_cache_version";
    if (typeof window === "undefined") return;

    const current = window.localStorage.getItem(cacheKey);
    if (current === cacheVersion) return;

    window.localStorage.setItem(cacheKey, cacheVersion);

    const cleanup = async () => {
      try {
        if ("serviceWorker" in navigator) {
          const registrations = await navigator.serviceWorker.getRegistrations();
          await Promise.all(registrations.map((registration) => registration.unregister()));
        }
        if ("caches" in window) {
          const keys = await caches.keys();
          await Promise.all(keys.map((key) => caches.delete(key)));
        }
      } finally {
        window.location.reload();
      }
    };

    void cleanup();
  }, []);

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
