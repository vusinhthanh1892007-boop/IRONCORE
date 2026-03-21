"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
    CommandShortcut,
} from "@/components/ui/command";
import {
    Settings,
    User,
    LayoutDashboard,
    Box,
    TerminalSquare,
    Network,
    PlugZap,
    Bot,
    MessageSquare,
    Shield,
    Activity
} from "lucide-react";

export function CommandPalette() {
    const [open, setOpen] = React.useState(false);
    const router = useRouter();

    React.useEffect(() => {
        const down = (e: KeyboardEvent) => {
            if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                setOpen((open) => !open);
            }
        };

        document.addEventListener("keydown", down);
        return () => document.removeEventListener("keydown", down);
    }, []);

    const runCommand = React.useCallback((command: () => unknown) => {
        setOpen(false);
        command();
    }, []);

    return (
        <>
            <CommandDialog open={open} onOpenChange={setOpen}>
                <CommandInput placeholder="Type a command or search..." />
                <CommandList>
                    <CommandEmpty>No results found.</CommandEmpty>
                    <CommandGroup heading="Control Plane">
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/"))}
                        >
                            <LayoutDashboard className="mr-2 h-4 w-4" />
                            <span>Overview</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/nodes"))}
                        >
                            <Network className="mr-2 h-4 w-4" />
                            <span>Nodes & Clusters</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/monitoring/telemetry"))}
                        >
                            <Activity className="mr-2 h-4 w-4" />
                            <span>Real-time Telemetry</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/monitoring/logs"))}
                        >
                            <TerminalSquare className="mr-2 h-4 w-4" />
                            <span>System Logs</span>
                        </CommandItem>
                    </CommandGroup>
                    <CommandSeparator />

                    <CommandGroup heading="Agents & Ecosystem">
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/agents"))}
                        >
                            <Bot className="mr-2 h-4 w-4" />
                            <span>Agent Management</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/skills"))}
                        >
                            <Box className="mr-2 h-4 w-4" />
                            <span>Skill Registry</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/ecosystem/channels"))}
                        >
                            <MessageSquare className="mr-2 h-4 w-4" />
                            <span>Channel Connectors</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/ecosystem/plugins"))}
                        >
                            <PlugZap className="mr-2 h-4 w-4" />
                            <span>Plugins Hub</span>
                        </CommandItem>
                    </CommandGroup>
                    <CommandSeparator />

                    <CommandGroup heading="IronCore Security">
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/security/policies"))}
                        >
                            <Shield className="mr-2 h-4 w-4" />
                            <span>Policy Engine</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/settings"))}
                        >
                            <Settings className="mr-2 h-4 w-4" />
                            <span>Gateway & API Settings</span>
                            <CommandShortcut>⌘S</CommandShortcut>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => runCommand(() => router.push("/profile"))}
                        >
                            <User className="mr-2 h-4 w-4" />
                            <span>Operator Profile</span>
                        </CommandItem>
                    </CommandGroup>
                </CommandList>
            </CommandDialog>
        </>
    );
}
