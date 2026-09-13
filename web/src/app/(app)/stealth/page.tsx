"use client";

import * as React from "react";
import {
  Camera,
  Code as Code2,
  Eye,
  Globe,
  CircleNotch as Loader2,
  CursorClick as MousePointerClick,
  ArrowClockwise as RefreshCw,
  ShieldCheck,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface StealthStatus {
  active_sessions: number;
  pages_visited: number;
  actions: number;
}

interface TaskResult {
  success: boolean;
  url: string;
  screenshot_b64?: string;
  text?: string;
  html?: string;
  error?: string;
  elapsed_ms?: number;
}

export default function StealthPage() {
  const [url, setUrl] = React.useState("");
  const [task, setTask] = React.useState<"screenshot" | "scrape">("screenshot");
  const [selector, setSelector] = React.useState("body");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<TaskResult | null>(null);
  const [status, setStatus] = React.useState<StealthStatus>({
    active_sessions: 0,
    pages_visited: 0,
    actions: 0,
  });
  const [statusLoading, setStatusLoading] = React.useState(false);

  const apiKey =
    typeof window !== "undefined"
      ? (localStorage.getItem("ironcore_api_key") ?? "")
      : "";

  const fetchStatus = React.useCallback(async () => {
    setStatusLoading(true);
    try {
      const res = await fetch("/api/stealth", {
        headers: { "X-IronCore-API-Key": apiKey },
        cache: "no-store",
      });
      if (res.ok) {
        const data: StealthStatus = await res.json();
        setStatus(data);
      }
    } catch {
      // backend offline
    } finally {
      setStatusLoading(false);
    }
  }, [apiKey]);

  React.useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleRun = async () => {
    if (!url.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const body: Record<string, unknown> = { task, url: url.trim() };
      if (task === "scrape" && selector) body.selector = selector;

      const res = await fetch("/api/stealth", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-IronCore-API-Key": apiKey,
        },
        body: JSON.stringify(body),
      });
      const data: TaskResult = await res.json();
      setResult(data);
      await fetchStatus();
    } catch (e: unknown) {
      setResult({ success: false, url: url.trim(), error: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold">Stealth Browser</h1>
        <p className="text-sm text-muted-foreground">
          Headless anti-bot browser for screenshots and scraping data from protected sites.
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { icon: Eye, label: "Active sessions", value: String(status.active_sessions) },
          { icon: Globe, label: "Pages visited", value: String(status.pages_visited) },
          { icon: MousePointerClick, label: "Actions", value: String(status.actions) },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-3">
              <Icon className="h-5 w-5 text-primary" />
              <div>
                <div className="text-xs text-muted-foreground">{label}</div>
                <div className="text-2xl font-bold">{value}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Task panel */}
      <div className="rounded-xl border border-border bg-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="font-semibold text-sm">Run task</div>
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchStatus}
            disabled={statusLoading}
          >
            <RefreshCw className={cn("h-4 w-4", statusLoading && "animate-spin")} />
          </Button>
        </div>

        {/* Task type toggle */}
        <div className="flex gap-2">
          {(["screenshot", "scrape"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTask(t)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
                task === t
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-muted text-muted-foreground hover:bg-accent"
              )}
            >
              {t === "screenshot" ? (
                <Camera className="h-3.5 w-3.5" />
              ) : (
                <Code2 className="h-3.5 w-3.5" />
              )}
              {t === "screenshot" ? "Screenshot" : "Scrape data"}
            </button>
          ))}
        </div>

        {/* URL input */}
        <div className="space-y-1.5">
          <Label className="text-xs">Website URL</Label>
          <div className="flex gap-2">
            <Input
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !busy && handleRun()}
              className="font-mono text-xs"
            />
            <Button onClick={handleRun} disabled={busy || !url.trim()} className="shrink-0">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Run"}
            </Button>
          </div>
        </div>

        {/* Scrape selector */}
        {task === "scrape" && (
          <div className="space-y-1.5">
            <Label className="text-xs">CSS Selector (default: body)</Label>
            <Input
              placeholder="body, #content, .article-text"
              value={selector}
              onChange={(e) => setSelector(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
        )}

        {/* Anti-detection badge */}
        <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
          Fingerprint spoofing · WebGL noise · Canvas noise · Cloudflare bypass
        </div>
      </div>

      {/* Result */}
      {result && (
        <div className="rounded-xl border border-border bg-card p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-sm">Result</div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 font-medium",
                  result.success
                    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                    : "bg-destructive/15 text-destructive"
                )}
              >
                {result.success ? "Success" : "Error"}
              </span>
              {result.elapsed_ms && (
                <span>{result.elapsed_ms.toFixed(0)} ms</span>
              )}
            </div>
          </div>

          {result.error && (
            <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-xs text-destructive">
              {result.error}
            </div>
          )}

          {/* Screenshot preview */}
          {result.screenshot_b64 && (
            <div className="overflow-hidden rounded-lg border border-border">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`data:image/png;base64,${result.screenshot_b64}`}
                alt={`Screenshot of ${result.url}`}
                className="w-full"
              />
            </div>
          )}

          {/* Scraped text */}
          {result.text && (
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">
                Content ({result.text.length} chars)
              </div>
              <pre className="max-h-96 overflow-y-auto rounded-lg border border-border bg-muted px-4 py-3 text-xs whitespace-pre-wrap">
                {result.text}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
