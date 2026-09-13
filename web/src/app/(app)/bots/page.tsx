"use client";

import * as React from "react";
import {
  Robot as Bot,
  CheckCircle,
  Circle,
  CircleNotch as Loader2,
  ArrowClockwise as RefreshCw,
  Gear as Settings,
  XCircle,
  PaperPlaneTilt as Send,
  ChatCircle as MessageCircle,
  TelegramLogo,
  DiscordLogo,
  MessengerLogo,
  WhatsappLogo,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ChannelStatus {
  name: string;
  platform: string;
  running: boolean;
  configured: boolean;
}

interface BotConfig {
  access_token: string;
  app_secret: string;
  refresh_token: string;
  verify_token: string;
  phone_number_id: string;
  allowed_user_ids: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  telegram: <TelegramLogo className="h-5 w-5 text-[#26A5E4]" weight="fill" />,
  zalo: (
    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#0068FF] text-[8px] font-black text-white leading-none">
      Z
    </span>
  ),
  discord: <DiscordLogo className="h-5 w-5 text-[#5865F2]" weight="fill" />,
  messenger: <MessengerLogo className="h-5 w-5 text-[#0078FF]" weight="fill" />,
  whatsapp: <WhatsappLogo className="h-5 w-5 text-[#25D366]" weight="fill" />,
};

const PLATFORM_DOCS: Record<string, { label: string; envVar: string; help: string }> = {
  telegram: {
    label: "Bot Token",
    envVar: "TELEGRAM_BOT_TOKEN",
    help: "Get token from @BotFather on Telegram",
  },
  zalo: {
    label: "OA Access Token",
    envVar: "ZALO_OA_ACCESS_TOKEN",
    help: "From Zalo Developer Console → Official Account → Access Token",
  },
  discord: {
    label: "Bot Token",
    envVar: "DISCORD_BOT_TOKEN",
    help: "From Discord Developer Portal → Applications → Bot → Token",
  },
  messenger: {
    label: "Page Access Token",
    envVar: "MESSENGER_PAGE_ACCESS_TOKEN",
    help: "From Meta Developer Console → App → Messenger → Configuration → Page Access Token",
  },
  whatsapp: {
    label: "Access Token",
    envVar: "WHATSAPP_ACCESS_TOKEN",
    help: "From Meta Developer Console → App → WhatsApp → Configuration → Access Token",
  },
};

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function BotsPage() {
  const [channels, setChannels] = React.useState<ChannelStatus[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [configOpen, setConfigOpen] = React.useState<string | null>(null);
  const [configs, setConfigs] = React.useState<Record<string, BotConfig>>({});
  const [actionBusy, setActionBusy] = React.useState<Record<string, boolean>>({});

  const apiKey =
    typeof window !== "undefined"
      ? (localStorage.getItem("ironcore_api_key") ?? "")
      : "";

  const fetchStatus = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/bots", {
        headers: { "X-IronCore-API-Key": apiKey },
        cache: "no-store",
      });
      const data: ChannelStatus[] = await res.json();
      setChannels(data);
    } catch {
      // backend offline — show empty state
      setChannels([
        { name: "telegram", platform: "Telegram", running: false, configured: false },
        { name: "zalo", platform: "Zalo OA", running: false, configured: false },
        { name: "discord", platform: "Discord", running: false, configured: false },
        { name: "messenger", platform: "Messenger", running: false, configured: false },
        { name: "whatsapp", platform: "WhatsApp", running: false, configured: false },
      ]);
    } finally {
      setLoading(false);
    }
  }, [apiKey]);

  React.useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleToggle = async (channel: ChannelStatus) => {
    const action = channel.running ? "stop" : "start";
    setActionBusy((prev) => ({ ...prev, [channel.name]: true }));
    try {
      const cfg = configs[channel.name] ?? {};
      await fetch("/api/bots", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-IronCore-API-Key": apiKey,
        },
        body: JSON.stringify({
          channel: channel.name,
          action,
          access_token: cfg.access_token ?? "",
          app_secret: cfg.app_secret ?? "",
          refresh_token: cfg.refresh_token ?? "",
          verify_token: cfg.verify_token ?? "",
          phone_number_id: cfg.phone_number_id ?? "",
          allowed_user_ids: cfg.allowed_user_ids ?? "",
        }),
      });
      await fetchStatus();
    } finally {
      setActionBusy((prev) => ({ ...prev, [channel.name]: false }));
    }
  };

  const runningCount = channels.filter((c) => c.running).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Bot Channels</h1>
          <p className="text-sm text-muted-foreground">
            Connect IronCore AI to messaging platforms.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchStatus} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </Button>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { icon: Bot, label: "Active bots", value: String(runningCount) },
          {
            icon: MessageCircle,
            label: "Configured",
            value: String(channels.filter((c) => c.configured).length),
          },
          { icon: Send, label: "Platforms", value: String(channels.length) },
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

      {/* Channel cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {channels.map((ch) => {
          const busy = actionBusy[ch.name] ?? false;
          const isOpen = configOpen === ch.name;
          const cfg = configs[ch.name] ?? {
            access_token: "",
            app_secret: "",
            refresh_token: "",
            verify_token: "",
            phone_number_id: "",
            allowed_user_ids: "",
          };
          const doc = PLATFORM_DOCS[ch.name];

          return (
            <div
              key={ch.name}
              className="rounded-xl border border-border bg-card p-5 space-y-4"
            >
              {/* Platform header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {PLATFORM_ICONS[ch.name] ?? <Bot className="h-5 w-5" />}
                  <span className="font-medium">{ch.platform}</span>
                </div>
                <StatusBadge running={ch.running} />
              </div>

              {/* Config label */}
              <div className="text-xs text-muted-foreground">
                {ch.configured ? (
                  <span className="flex items-center gap-1 text-emerald-500">
                    <CheckCircle className="h-3 w-3" /> Token configured via environment
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-red-400">
                    <XCircle className="h-3 w-3" /> Not configured — enter token below
                  </span>
                )}
              </div>

              {/* Collapsible config form */}
              <div>
                <button
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => setConfigOpen(isOpen ? null : ch.name)}
                >
                  <Settings className="h-3 w-3" />
                  {isOpen ? "Hide config" : "Configure token"}
                </button>

                {isOpen && (
                  <div className="mt-3 space-y-3">
                    <div className="space-y-1">
                      <Label className="text-xs">{doc?.label ?? "Token"}</Label>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        placeholder={doc?.envVar ?? "token"}
                        value={cfg.access_token}
                        onChange={(e) =>
                          setConfigs((prev) => ({
                            ...prev,
                            [ch.name]: { ...cfg, access_token: e.target.value },
                          }))
                        }
                        className="h-8 text-xs font-mono"
                      />
                      {doc?.help && (
                        <p className="text-[10px] text-muted-foreground">{doc.help}</p>
                      )}
                    </div>

                    {ch.name === "zalo" && (
                      <>
                        <div className="space-y-1">
                          <Label className="text-xs">App Secret</Label>
                          <Input
                            type="password"
                            autoComplete="new-password"
                            placeholder="ZALO_OA_APP_SECRET"
                            value={cfg.app_secret}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, app_secret: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Refresh Token (optional)</Label>
                          <Input
                            type="password"
                            autoComplete="new-password"
                            placeholder="ZALO_OA_REFRESH_TOKEN"
                            value={cfg.refresh_token}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, refresh_token: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                        </div>
                      </>
                    )}

                    {ch.name === "messenger" && (
                      <>
                        <div className="space-y-1">
                          <Label className="text-xs">Verify Token</Label>
                          <Input
                            type="text"
                            autoComplete="off"
                            placeholder="MESSENGER_VERIFY_TOKEN"
                            value={cfg.verify_token}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, verify_token: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                          <p className="text-[10px] text-muted-foreground">
                            Any string you set in Meta → Webhook → Verify Token
                          </p>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">App Secret (optional)</Label>
                          <Input
                            type="password"
                            autoComplete="new-password"
                            placeholder="MESSENGER_APP_SECRET"
                            value={cfg.app_secret}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, app_secret: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                        </div>
                      </>
                    )}

                    {ch.name === "whatsapp" && (
                      <>
                        <div className="space-y-1">
                          <Label className="text-xs">Phone Number ID</Label>
                          <Input
                            type="text"
                            autoComplete="off"
                            placeholder="WHATSAPP_PHONE_NUMBER_ID"
                            value={cfg.phone_number_id}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, phone_number_id: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                          <p className="text-[10px] text-muted-foreground">
                            Meta Developer Console → WhatsApp → API Setup → Phone Number ID
                          </p>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Verify Token</Label>
                          <Input
                            type="text"
                            autoComplete="off"
                            placeholder="WHATSAPP_VERIFY_TOKEN"
                            value={cfg.verify_token}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, verify_token: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">App Secret (optional)</Label>
                          <Input
                            type="password"
                            autoComplete="new-password"
                            placeholder="WHATSAPP_APP_SECRET"
                            value={cfg.app_secret}
                            onChange={(e) =>
                              setConfigs((prev) => ({
                                ...prev,
                                [ch.name]: { ...cfg, app_secret: e.target.value },
                              }))
                            }
                            className="h-8 text-xs font-mono"
                          />
                        </div>
                      </>
                    )}

                    <div className="space-y-1">
                      <Label className="text-xs">
                        Allowed user IDs (comma-separated, empty = allow all)
                      </Label>
                      <Input
                        type="text"
                        placeholder="123456789, 987654321"
                        value={cfg.allowed_user_ids}
                        onChange={(e) =>
                          setConfigs((prev) => ({
                            ...prev,
                            [ch.name]: { ...cfg, allowed_user_ids: e.target.value },
                          }))
                        }
                        className="h-8 text-xs font-mono"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Start / Stop button */}
              <Button
                size="sm"
                className="w-full"
                variant={ch.running ? "destructive" : "default"}
                disabled={busy}
                onClick={() => handleToggle(ch)}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : ch.running ? (
                  "Stop bot"
                ) : (
                  "Start bot"
                )}
              </Button>

              {/* Webhook URL hint for Zalo */}
              {ch.name === "zalo" && ch.running && (
                <div className="rounded-lg border border-border bg-muted px-3 py-2 text-[10px] text-muted-foreground">
                  Webhook URL: <code className="text-foreground">/v1/webhooks/zalo</code>
                  <br />
                  Register this URL in{" "}
                  <a
                    href="https://developers.zalo.me"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    Zalo Developer Console
                  </a>
                </div>
              )}

              {/* Webhook URL hint for Messenger */}
              {ch.name === "messenger" && ch.running && (
                <div className="rounded-lg border border-border bg-muted px-3 py-2 text-[10px] text-muted-foreground">
                  Webhook URL: <code className="text-foreground">/v1/webhooks/messenger</code>
                  <br />
                  Register in{" "}
                  <a
                    href="https://developers.facebook.com/apps"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    Meta Developer Console
                  </a>{" "}
                  → Messenger → Webhooks
                </div>
              )}

              {/* Webhook URL hint for WhatsApp */}
              {ch.name === "whatsapp" && ch.running && (
                <div className="rounded-lg border border-border bg-muted px-3 py-2 text-[10px] text-muted-foreground">
                  Webhook URL: <code className="text-foreground">/v1/webhooks/whatsapp</code>
                  <br />
                  Register in{" "}
                  <a
                    href="https://developers.facebook.com/apps"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline"
                  >
                    Meta Developer Console
                  </a>{" "}
                  → WhatsApp → Configuration
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* How it works */}
      <div className="rounded-xl border border-border bg-card p-6 space-y-3">
        <div className="font-semibold text-sm">How it works</div>
        <ol className="list-decimal list-inside space-y-2 text-sm text-muted-foreground">
          <li>
            Users send messages on{" "}
            <strong className="text-foreground">Telegram</strong>,{" "}
            <strong className="text-foreground">Zalo</strong>,{" "}
            <strong className="text-foreground">Messenger</strong>, and{" "}
            <strong className="text-foreground">WhatsApp</strong> → the bot receives them.
          </li>
          <li>
            Messages are forwarded to the{" "}
            <strong className="text-foreground">IronCore Engine</strong> for AI processing.
          </li>
          <li>
            The engine replies → Bot sends the response back in the{" "}
            <strong className="text-foreground">same conversation</strong>.
          </li>
          <li>
            Each user has a <strong className="text-foreground">separate session</strong>{" "}
            (telegram:user_id / zalo:user_id) to preserve conversation context.
          </li>
        </ol>
      </div>
    </div>
  );
}

// ── StatusBadge ───────────────────────────────────────────────────────────────

function StatusBadge({ running }: { running: boolean }) {
  return (
    <span
      className={cn(
        "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
        running
          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          : "bg-muted text-muted-foreground"
      )}
    >
      {running ? (
        <>
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
          Running
        </>
      ) : (
        <>
          <Circle className="h-2.5 w-2.5" />
          Stopped
        </>
      )}
    </span>
  );
}
