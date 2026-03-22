"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Something went wrong
      </p>
      <h1 className="text-3xl font-semibold">IronCore UI Error</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        {error.message || "An unexpected error occurred. Please try again."}
      </p>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  );
}
