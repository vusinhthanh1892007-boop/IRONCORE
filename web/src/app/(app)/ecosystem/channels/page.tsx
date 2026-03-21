"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { DiscordLogo, SlackLogo, TelegramLogo, WhatsappLogo, Check, WifiHigh, WifiSlash } from "@phosphor-icons/react";
import { MessageSquare } from "lucide-react";
import { toast } from "sonner";

interface ChannelConfig {
    id: string;
    name: string;
    icon: React.ReactNode;
    enabled: boolean;
    status: "online" | "offline" | "configuring";
    description: string;
    fields: { name: string; label: string; placeholder: string; type: "text" | "password" }[];
}

export default function ChannelsPage() {
    const [channels, setChannels] = useState<ChannelConfig[]>([
        {
            id: "discord",
            name: "Discord Bot",
            icon: <DiscordLogo weight="duotone" className="h-6 w-6 text-[#5865F2]" />,
            enabled: true,
            status: "online",
            description: "Connect IronCore to your Discord server via Bot Token.",
            fields: [
                { name: "botToken", label: "Bot Token", placeholder: "MTAx...", type: "password" },
                { name: "clientId", label: "Client ID", placeholder: "Application ID", type: "text" },
            ]
        },
        {
            id: "slack",
            name: "Slack App",
            icon: <SlackLogo weight="duotone" className="h-6 w-6 text-[#E01E5A]" />,
            enabled: false,
            status: "offline",
            description: "Deploy the agent as a Slack workspace integration.",
            fields: [
                { name: "botToken", label: "Bot User OAuth Token", placeholder: "xoxb-...", type: "password" },
                { name: "signingSecret", label: "Signing Secret", placeholder: "...", type: "password" },
            ]
        },
        {
            id: "telegram",
            name: "Telegram Bot",
            icon: <TelegramLogo weight="duotone" className="h-6 w-6 text-[#229ED9]" />,
            enabled: false,
            status: "offline",
            description: "Interact with IronCore via Telegram chats and groups.",
            fields: [
                { name: "botToken", label: "Bot Token (from BotFather)", placeholder: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", type: "password" },
            ]
        },
        {
            id: "whatsapp",
            name: "WhatsApp Cloud API",
            icon: <WhatsappLogo weight="duotone" className="h-6 w-6 text-[#25D366]" />,
            enabled: false,
            status: "offline",
            description: "Connect to Meta's WhatsApp Cloud API for business messaging.",
            fields: [
                { name: "phoneId", label: "Phone Number ID", placeholder: "10123456789...", type: "text" },
                { name: "accessToken", label: "Permanent Access Token", placeholder: "EAAB...", type: "password" },
                { name: "verifyToken", label: "Webhook Verify Token", placeholder: "my-custom-token", type: "password" },
            ]
        }
    ]);

    const toggleChannel = (id: string, current: boolean) => {
        setChannels(prev => prev.map(c =>
            c.id === id ? { ...c, enabled: !current, status: !current ? "configuring" : "offline" } : c
        ));
        if (!current) {
            toast.success(`Enabled configuration for ${id}.`);
        } else {
            toast.info(`Disconnected ${id} connector.`);
        }
    };

    const handleSave = (id: string) => {
        setChannels(prev => prev.map(c =>
            c.id === id ? { ...c, status: "online" } : c
        ));
        toast.success(`Successfully connected ${id} channel endpoint.`);
    };

    return (
        <div className="flex w-full flex-col gap-8 max-w-4xl pt-4">
            <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground flex items-center gap-3">
                    <MessageSquare className="h-8 w-8 text-primary" />
                    Channel Connectors
                </h1>
                <p className="text-sm text-muted-foreground">
                    Deploy your IronCore fleet to external communication platforms. Configure Webhooks and Tokens below to establish 2-way bridges.
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {channels.map((channel) => (
                    <div key={channel.id} className="rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:shadow-md">
                        <div className="flex items-center justify-between mb-4">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-muted rounded-lg border border-border/50">
                                    {channel.icon}
                                </div>
                                <div>
                                    <h3 className="font-medium text-foreground">{channel.name}</h3>
                                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-0.5">
                                        {channel.status === "online" ? (
                                            <><WifiHigh className="text-emerald-500" /> Connected</>
                                        ) : channel.status === "configuring" ? (
                                            <><WifiHigh className="text-amber-500 animate-pulse" /> Pending Setup</>
                                        ) : (
                                            <><WifiSlash /> Offline</>
                                        )}
                                    </div>
                                </div>
                            </div>
                            <Switch
                                checked={channel.enabled}
                                onCheckedChange={() => toggleChannel(channel.id, channel.enabled)}
                            />
                        </div>

                        <p className="text-sm text-muted-foreground mb-4 min-h-[40px]">
                            {channel.description}
                        </p>

                        {channel.enabled && (
                            <div className="space-y-4 pt-4 border-t border-border mt-2 animate-in fade-in slide-in-from-top-2">
                                {channel.fields.map(field => (
                                    <div key={field.name} className="space-y-1.5">
                                        <Label className="text-xs text-muted-foreground">{field.label}</Label>
                                        <Input
                                            type={field.type}
                                            placeholder={field.placeholder}
                                            className="h-8 text-sm"
                                            defaultValue={channel.status === "online" ? "•••••••••••••••••" : ""}
                                        />
                                    </div>
                                ))}

                                <div className="pt-2 flex justify-end">
                                    <Button size="sm" onClick={() => handleSave(channel.id)} className="gap-2">
                                        <Check className="h-4 w-4" />
                                        Save & Connect
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}
