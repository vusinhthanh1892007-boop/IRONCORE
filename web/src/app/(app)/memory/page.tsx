"use client";

import { Brain, GitBranch, MagnifyingGlass as Search } from "@phosphor-icons/react";

export default function MemoryPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">GraphRAG Memory</h1>
        <p className="text-sm text-muted-foreground">Knowledge graph and retrieval-augmented generation index.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { icon: Brain, label: "Indexed nodes", value: "4,821" },
          { icon: GitBranch, label: "Graph edges", value: "12,340" },
          { icon: Search, label: "RAG queries today", value: "68" },
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

      <div className="rounded-xl border border-border bg-card p-6">
        <div className="text-sm font-semibold">Memory Graph</div>
        <div className="mt-6 flex h-40 items-center justify-center rounded-lg border border-dashed border-border text-xs text-muted-foreground">
          Graph visualisation coming soon
        </div>
      </div>
    </div>
  );
}
