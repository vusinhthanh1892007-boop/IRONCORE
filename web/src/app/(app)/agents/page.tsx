"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Robot, Code, PaintBrush, HeadCircuit, Gear, Cpu, ShieldWarning, FloppyDisk } from "@phosphor-icons/react";
import { toast } from "sonner";

interface AgentProfile {
    id: string;
    name: string;
    role: string;
    icon: React.ReactNode;
    active: boolean;
    model: string;
    temperature: number;
    systemPrompt: string;
    skills: { name: string; enabled: boolean }[];
}

export default function AgentsPage() {
    const [agents, setAgents] = useState<AgentProfile[]>([
        {
            id: "orchestrator",
            name: "The Orchestrator",
            role: "System Router & Task Delegator",
            icon: <HeadCircuit weight="duotone" className="h-6 w-6 text-purple-500" />,
            active: true,
            model: "gpt-4o",
            temperature: 0.2,
            systemPrompt: "You are the IronCore Orchestrator. You do not write code. You analyze user intent, break it down into steps, and delegate it to the specialized sub-agents (Designer, Coder, Reviewer).",
            skills: [
                { name: "GraphRAG Memory Access", enabled: true },
                { name: "Web Searching", enabled: false },
                { name: "Agent Spawning", enabled: true }
            ]
        },
        {
            id: "designer",
            name: "UI/UX Designer",
            role: "Frontend & Layout Specialist",
            icon: <PaintBrush weight="duotone" className="h-6 w-6 text-pink-500" />,
            active: true,
            model: "claude-sonnet-4-6",
            temperature: 0.7,
            systemPrompt: "You are an elite UI/UX developer. You focus on creating stunning, accessible, and highly responsive components using TailwindCSS and Shadcn/UI.",
            skills: [
                { name: "Read Web Files", enabled: true },
                { name: "VLM Visual Analysis", enabled: true }
            ]
        },
        {
            id: "coder",
            name: "Backend Optimizer",
            role: "Logic & Architecture Engineer",
            icon: <Code weight="duotone" className="h-6 w-6 text-emerald-500" />,
            active: true,
            model: "gpt-5.4-pro",
            temperature: 0.1,
            systemPrompt: "You are the IronCore Backend Optimizer. Your code must be robust, asynchronous, and follow the highest security standards. Never expose secrets.",
            skills: [
                { name: "LSP Syntax Editing", enabled: true },
                { name: "Execute Terminals", enabled: true },
                { name: "Database Admin", enabled: false }
            ]
        }
    ]);

    const [selectedAgent, setSelectedAgent] = useState<string>(agents[0].id);
    const activeAgent = agents.find(a => a.id === selectedAgent)!;

    const updateAgent = (updates: Partial<AgentProfile>) => {
        setAgents(prev => prev.map(a => a.id === selectedAgent ? { ...a, ...updates } : a));
    };

    const handleSave = () => {
        toast.success(`${activeAgent.name} configuration saved securely.`);
    };

    return (
        <div className="flex w-full flex-col gap-6 max-w-6xl pt-4">
            <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground flex items-center gap-3">
                    <Robot className="h-8 w-8 text-primary" weight="duotone" />
                    Agent Swarm Management
                </h1>
                <p className="text-sm text-muted-foreground">
                    Configure the roles, permissions, and logic boundaries for your autonomous workers.
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
                {/* Left Sidebar - Agent List */}
                <div className="md:col-span-4 flex flex-col gap-3">
                    {agents.map(agent => (
                        <button
                            key={agent.id}
                            onClick={() => setSelectedAgent(agent.id)}
                            className={`flex items-start gap-4 p-4 rounded-xl text-left transition-all border ${selectedAgent === agent.id
                                    ? "border-primary bg-primary/5 shadow-sm"
                                    : "border-border bg-card hover:bg-card/70 hover:border-primary/30"
                                }`}
                        >
                            <div className="mt-0.5">{agent.icon}</div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between">
                                    <h3 className="font-semibold text-sm truncate">{agent.name}</h3>
                                    <div className={`h-2 w-2 rounded-full ${agent.active ? "bg-emerald-500" : "bg-muted-foreground"}`} />
                                </div>
                                <p className="text-xs text-muted-foreground truncate mt-0.5">{agent.role}</p>
                                <div className="mt-2 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-background text-[10px] font-mono border border-border">
                                    <Cpu className="h-3 w-3" />
                                    {agent.model}
                                </div>
                            </div>
                        </button>
                    ))}
                    <Button variant="outline" className="w-full mt-2 border-dashed">
                        + Spawn New Agent
                    </Button>
                </div>

                {/* Right Pane - Agent Config Editor */}
                <div className="md:col-span-8 bg-card border border-border rounded-xl p-6 shadow-sm">
                    <div className="flex items-center justify-between mb-6 pb-6 border-b border-border">
                        <div>
                            <h2 className="text-xl font-semibold flex items-center gap-2">
                                {activeAgent.icon}
                                {activeAgent.name} Settings
                            </h2>
                            <p className="text-sm text-muted-foreground mt-1">Runtime ID: <code className="text-xs">agent-{activeAgent.id}-v2</code></p>
                        </div>
                        <div className="flex items-center gap-3">
                            <Label className="text-sm font-medium">Status Active</Label>
                            <Switch checked={activeAgent.active} onCheckedChange={(v) => updateAgent({ active: v })} />
                        </div>
                    </div>

                    <div className="space-y-6">
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label>Backing Model</Label>
                                <Input
                                    value={activeAgent.model}
                                    onChange={(e) => updateAgent({ model: e.target.value })}
                                    className="font-mono text-xs"
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>Temperature ({activeAgent.temperature})</Label>
                                <div className="flex items-center gap-4 h-10 w-full rounded-md border border-input bg-transparent px-3 py-1 shadow-sm">
                                    <input
                                        type="range" min="0" max="1" step="0.1"
                                        value={activeAgent.temperature}
                                        onChange={(e) => updateAgent({ temperature: parseFloat(e.target.value) })}
                                        className="w-full flex-1"
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center justify-between">
                                <Label>Core System Prompt / Directives</Label>
                                <ShieldWarning className="h-4 w-4 text-amber-500" />
                            </div>
                            <Textarea
                                value={activeAgent.systemPrompt}
                                onChange={(e) => updateAgent({ systemPrompt: e.target.value })}
                                className="min-h-[120px] font-mono text-sm leading-relaxed text-muted-foreground focus:text-foreground transition-colors"
                                placeholder="You are a helpful assistant..."
                            />
                        </div>

                        <div className="space-y-3 pt-2">
                            <Label className="flex items-center gap-2">
                                <Gear className="h-4 w-4" />
                                Vetted Skills / Capabilities
                            </Label>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {activeAgent.skills.map((skill, idx) => (
                                    <div key={skill.name} className="flex items-center justify-between p-3 rounded-lg border border-border/50 bg-background/50 text-sm">
                                        <span className="font-medium text-muted-foreground">{skill.name}</span>
                                        <Switch
                                            checked={skill.enabled}
                                            onCheckedChange={(v) => {
                                                const newSkills = [...activeAgent.skills];
                                                newSkills[idx].enabled = v;
                                                updateAgent({ skills: newSkills });
                                            }}
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="pt-6 border-t border-border flex justify-end gap-3">
                            <Button variant="ghost">Discard Draft</Button>
                            <Button className="gap-2" onClick={handleSave}>
                                <FloppyDisk className="h-4 w-4" /> Save Configuration
                            </Button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
