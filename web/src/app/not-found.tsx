import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
        404
      </p>
      <h1 className="text-3xl font-semibold">Page not found</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        The route you are looking for is not part of the IronCore console.
      </p>
      <Button asChild>
        <Link href="/chat">Back to chat</Link>
      </Button>
    </div>
  );
}
