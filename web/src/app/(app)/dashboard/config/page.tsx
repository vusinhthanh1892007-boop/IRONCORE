"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";

interface PluginToggle {
  id: string;
  name: string;
  enabled: boolean;
}

const initialPlugins: PluginToggle[] = [
  { id: "optimizer", name: "Optimizer", enabled: true },
  { id: "scheduler", name: "Scheduler", enabled: true },
  { id: "siem-stream", name: "SIEM Stream", enabled: true },
  { id: "stealth-browser", name: "Stealth Browser", enabled: false },
];

export default function DashboardConfigPage() {
  const [plugins, setPlugins] = React.useState<PluginToggle[]>(initialPlugins);

  const togglePlugin = (id: string, enabled: boolean) => {
    if (!enabled) {
      const ok = window.confirm("Disable plugin? This can interrupt runtime tasks.");
      if (!ok) return;
    }
    setPlugins((prev) => prev.map((p) => (p.id === id ? { ...p, enabled } : p)));
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Runtime Config</h1>
        <p className="text-sm text-muted-foreground">Plugins, policies, env profiles, and masked secret bindings.</p>
      </div>

      <ControlPlaneNav />

      <Card className="border border-border bg-card p-5">
        <Tabs defaultValue="plugins">
          <TabsList>
            <TabsTrigger value="plugins">Plugins</TabsTrigger>
            <TabsTrigger value="policies">Policies</TabsTrigger>
            <TabsTrigger value="env">Env Profile</TabsTrigger>
            <TabsTrigger value="secrets">Secrets Binding</TabsTrigger>
          </TabsList>

          <TabsContent value="plugins" className="mt-4 space-y-3">
            {plugins.map((plugin) => (
              <div key={plugin.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                <div>
                  <div className="font-medium">{plugin.name}</div>
                  <div className="text-xs text-muted-foreground">id: {plugin.id}</div>
                </div>
                <Switch checked={plugin.enabled} onCheckedChange={(v) => togglePlugin(plugin.id, v)} />
              </div>
            ))}
          </TabsContent>

          <TabsContent value="policies" className="mt-4 space-y-2">
            {["prompt_firewall", "rate_limit", "dlp", "rbac"].map((p) => (
              <div key={p} className="flex items-center justify-between rounded-lg border border-border p-3 text-sm">
                <span>{p}</span>
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-500">active</span>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="env" className="mt-4">
            <div className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
              Current profile: <span className="text-foreground">enterprise-production</span>
            </div>
          </TabsContent>

          <TabsContent value="secrets" className="mt-4 space-y-2">
            {[
              { key: "OPENAI_API_KEY", service: "llm-bridge" },
              { key: "SENTRY_DSN", service: "monitoring" },
              { key: "SLACK_WEBHOOK", service: "hitl-notifier" },
            ].map((s) => (
              <div key={s.key} className="rounded-lg border border-border p-3 text-sm">
                <div className="font-mono text-xs">{s.key}</div>
                <div className="text-xs text-muted-foreground">service: {s.service} · present: true</div>
              </div>
            ))}
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  );
}
