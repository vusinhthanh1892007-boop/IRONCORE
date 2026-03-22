"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MagnifyingGlass, DownloadSimple, CheckCircle, Trash } from "@phosphor-icons/react";
import { PlugZap } from "lucide-react";
import { toast } from "sonner";

interface PluginInfo {
    id: string;
    name: string;
    version: string;
    author: string;
    description: string;
    installed: boolean;
    verified: boolean;
    downloads: string;
}

export default function PluginsPage() {
    const [search, setSearch] = useState("");
    const [plugins, setPlugins] = useState<PluginInfo[]>([
        {
            id: "plugin-github-tools",
            name: "GitHub Developer Tools",
            version: "v2.1.0",
            author: "IronCore Labs",
            description: "Provides full repository management, PR automation, and issue triage capabilities to the agent.",
            installed: true,
            verified: true,
            downloads: "124k+"
        },
        {
            id: "plugin-notion-sync",
            name: "Notion Knowledge Sync",
            version: "v1.0.4",
            author: "Community",
            description: "Two-way sync between agent GraphRAG memory and Notion workspace databases.",
            installed: false,
            verified: true,
            downloads: "42k+"
        },
        {
            id: "plugin-aws-cli",
            name: "AWS Infrastructure Control",
            version: "v3.0.1",
            author: "IronCore Labs",
            description: "Allows the agent to safely execute whitelisted AWS CLI commands for DevOps automation.",
            installed: false,
            verified: true,
            downloads: "89k+"
        },
        {
            id: "plugin-stripe-billing",
            name: "Stripe Assistant Hub",
            version: "v0.9.2-beta",
            author: "FinTech OS",
            description: "Manage subscriptions, generate payment links, and handle refunds autonomously (HITL required).",
            installed: true,
            verified: false,
            downloads: "12k+"
        }
    ]);

    const filtered = plugins.filter(p => p.name.toLowerCase().includes(search.toLowerCase()) || p.description.toLowerCase().includes(search.toLowerCase()));

    const toggleInstall = (id: string, currentlyInstalled: boolean) => {
        setPlugins(prev => prev.map(p => p.id === id ? { ...p, installed: !currentlyInstalled } : p));
        if (currentlyInstalled) {
            toast.info(`Uninstalled plugin: ${id}`);
        } else {
            toast.success(`Successfully installed plugin: ${id}`);
        }
    };

    return (
        <div className="flex w-full flex-col gap-6 max-w-4xl pt-4">
            <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground flex items-center gap-3">
                    <PlugZap className="h-8 w-8 text-primary" />
                    Plugins Hub
                </h1>
                <p className="text-sm text-muted-foreground">
                    Discover and install verified plugins to expand your IronCore Agent&apos;s capabilities and integrated skills.
                </p>
            </div>

            <div className="flex items-center gap-4 w-full relative">
                <MagnifyingGlass className="absolute left-3 text-muted-foreground h-5 w-5" />
                <Input
                    placeholder="Search for plugins by name or description..."
                    className="pl-10 h-11 bg-card border-border shadow-sm rounded-xl"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                />
                <Button variant="outline" className="h-11 rounded-xl">Registry Options</Button>
            </div>

            <div className="grid grid-cols-1 gap-4 pt-4">
                {filtered.map(plugin => (
                    <div key={plugin.id} className="group relative rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:bg-card/70 hover:border-primary/30">
                        <div className="flex justify-between items-start gap-4">
                            <div className="flex flex-col gap-1.5 flex-1">
                                <div className="flex items-center gap-3">
                                    <h3 className="text-base font-semibold text-foreground">{plugin.name}</h3>
                                    {plugin.verified && (
                                        <div className="flex items-center gap-1 text-[10px] uppercase font-bold tracking-wider text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded-full">
                                            <CheckCircle weight="fill" /> Verified
                                        </div>
                                    )}
                                </div>

                                <p className="text-sm text-muted-foreground line-clamp-2 pr-8">{plugin.description}</p>

                                <div className="flex items-center gap-4 text-xs text-muted-foreground mt-2 font-mono">
                                    <span>{plugin.version}</span>
                                    <span className="opacity-50">•</span>
                                    <span>By {plugin.author}</span>
                                    <span className="opacity-50">•</span>
                                    <span>{plugin.downloads} installs</span>
                                </div>
                            </div>

                            <div className="flex flex-col gap-2 items-end">
                                {plugin.installed ? (
                                    <Button
                                        variant="destructive"
                                        size="sm"
                                        className="w-[110px] gap-2 opacity-0 group-hover:opacity-100 transition-opacity"
                                        onClick={() => toggleInstall(plugin.id, true)}
                                    >
                                        <Trash className="h-4 w-4" /> Uninstall
                                    </Button>
                                ) : (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="w-[110px] gap-2 border-primary text-primary hover:bg-primary/10"
                                        onClick={() => toggleInstall(plugin.id, false)}
                                    >
                                        <DownloadSimple className="h-4 w-4" /> Install
                                    </Button>
                                )}
                                {plugin.installed && (
                                    <div className="text-xs text-muted-foreground bg-muted px-3 py-1.5 rounded-md border border-border/50 text-center w-[110px]">
                                        Installed
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
                {filtered.length === 0 && (
                    <div className="text-center py-12 text-muted-foreground">
                        <PlugZap className="h-12 w-12 mx-auto mb-3 opacity-20" />
                        <p>No plugins found matching &quot;{search}&quot;</p>
                    </div>
                )}
            </div>
        </div>
    );
}
