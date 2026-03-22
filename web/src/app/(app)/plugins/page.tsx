"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { ironCoreClient, type PluginInfo } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

const statusStyle = (status: PluginInfo["status"]) => {
  switch (status) {
    case "active":
      return "bg-emerald-500/10 text-emerald-500";
    case "error":
      return "bg-red-500/10 text-red-500";
    default:
      return "bg-zinc-500/10 text-zinc-400";
  }
};

export default function PluginsPage() {
  const { data: session } = useSession();
  const [query, setQuery] = React.useState("");
  const [installOpen, setInstallOpen] = React.useState(false);
  const [installUrl, setInstallUrl] = React.useState("");

  React.useEffect(() => {
    if (session?.apiKey) {
      ironCoreClient.setApiKey(session.apiKey);
    }
  }, [session?.apiKey]);

  const { data, isLoading } = useQuery({
    queryKey: ["plugins"],
    queryFn: () => ironCoreClient.getPlugins(),
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  const plugins = data ?? [];

  const filtered = plugins.filter((plugin) =>
    plugin.name.toLowerCase().includes(query.toLowerCase())
  );

  const handleInstall = () => {
    toast.error("Plugin install requires the backend plugin API to be online.");
  };

  const handleToggle = (plugin: PluginInfo) => {
    toast.error(`${plugin.name} can only be toggled when the backend plugin API is online.`);
  };

  const handleUninstall = (plugin: PluginInfo) => {
    toast.error(`${plugin.name} can only be uninstalled when the backend plugin API is online.`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Extensions
          </p>
          <h1 className="mt-2 text-3xl font-semibold">Plugin Manager</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Install, enable, and monitor plugins.
          </p>
        </div>
        <Dialog open={installOpen} onOpenChange={setInstallOpen}>
          <DialogTrigger asChild>
            <Button>Install plugin</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Install plugin</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  GitHub URL
                </label>
                <Input
                  placeholder="https://github.com/org/plugin"
                  value={installUrl}
                  onChange={(event) => setInstallUrl(event.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Or upload .zip
                </label>
                <Input
                  type="file"
                  accept=".zip"
                  onChange={() => undefined}
                />
              </div>
              <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-700">
                Security warning: plugins requesting NETWORK/BROWSER will require admin approval.
              </div>
              <Button onClick={handleInstall}>Install</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="border border-border/60 bg-background/80 p-4">
        <Input
          placeholder="Search plugins..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(isLoading ? [] : filtered).length === 0 ? (
          <Card className="col-span-full border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
            No plugins installed yet.
          </Card>
        ) : null}
        {filtered.map((plugin) => (
          <Card key={plugin.id} className="border border-border/60 bg-background/80 p-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-sm font-semibold">{plugin.name}</div>
                <div className="text-xs text-muted-foreground">v{plugin.version}</div>
              </div>
              <Badge className={statusStyle(plugin.status)}>{plugin.status}</Badge>
            </div>
            <div className="mt-3 text-xs text-muted-foreground">
              Tools: {plugin.tools_count}
            </div>
            <div className="mt-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                Enabled
                <Switch
                  checked={plugin.status === "active"}
                  onCheckedChange={() => handleToggle(plugin)}
                />
              </div>
              <Button variant="outline" size="sm" onClick={() => handleUninstall(plugin)}>
                Uninstall
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
