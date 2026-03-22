"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { useChatStore, type Session } from "@/store/chat-store";
import { cn } from "@/lib/utils";
import { PushPin as Pin, Plus } from "@phosphor-icons/react";

export function SessionSidebar() {
  const [query, setQuery] = React.useState("");
  const {
    sessions,
    activeSessionId,
    createSession,
    switchSession,
    renameSession,
    deleteSession,
    togglePinSession,
    messagesBySession,
  } = useChatStore();

  const filtered = sessions.filter((session) =>
    session.name.toLowerCase().includes(query.toLowerCase())
  );

  const pinnedFiltered = filtered.filter((s) => s.pinned);
  const normalFiltered = filtered.filter((s) => !s.pinned);

  const handleExport = (sessionId: string) => {
    const session = sessions.find((item) => item.id === sessionId);
    if (!session) return;

    const payload = {
      session,
      messages: messagesBySession[sessionId] ?? [],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${session.name.replace(/\s+/g, "-")}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const renderSession = (session: Session) => (
    <ContextMenu key={session.id}>
      <ContextMenuTrigger asChild>
        <div className="group relative flex items-center gap-1">
          <button
            type="button"
            onClick={() => switchSession(session.id)}
            className={cn(
              "min-w-0 flex-1 rounded-2xl border border-transparent px-3 py-2 text-left text-sm transition",
              session.id === activeSessionId
                ? "border-border bg-muted/70"
                : "hover:bg-muted/40"
            )}
          >
            <div className="flex items-center gap-1.5 font-medium">
              {session.pinned && <Pin className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-500" />}
              <span className="truncate">{session.name}</span>
            </div>
            <div className="text-xs text-muted-foreground">
              Updated {new Date(session.updatedAt).toLocaleDateString()}
            </div>
          </button>
          <button
            type="button"
            title={session.pinned ? "Unpin" : "Pin session"}
            onClick={() => togglePinSession(session.id)}
            className={cn(
              "absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 transition",
              session.pinned
                ? "text-amber-500 opacity-80 hover:opacity-100"
                : "text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-foreground"
            )}
          >
            <Pin className={cn("h-3.5 w-3.5", session.pinned && "fill-amber-400")} />
          </button>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-44">
        <ContextMenuItem onSelect={() => togglePinSession(session.id)}>
          {session.pinned ? "Unpin" : "Pin"}
        </ContextMenuItem>
        <ContextMenuItem
          onSelect={() => {
            const nextName = window.prompt("Rename session", session.name);
            if (nextName) renameSession(session.id, nextName);
          }}
        >
          Rename
        </ContextMenuItem>
        <ContextMenuItem onSelect={() => handleExport(session.id)}>
          Export
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={() => deleteSession(session.id)}>
          Delete
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );

  return (
    <aside className="flex h-full flex-col gap-4 rounded-3xl border border-border/60 bg-background/80 p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold">Sessions</div>
          <div className="text-xs text-muted-foreground">History &amp; drafts</div>
        </div>
        <Button size="icon" variant="outline" onClick={() => createSession()} title="New session">
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search sessions..."
        className="bg-background"
      />

      <div className="flex-1 space-y-4 overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-border/70 p-4 text-xs text-muted-foreground">
            No sessions found.
          </div>
        ) : null}

        {pinnedFiltered.length > 0 && (
          <div className="space-y-1">
            <div className="px-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Pinned
            </div>
            {pinnedFiltered.map(renderSession)}
          </div>
        )}

        {normalFiltered.length > 0 && (
          <div className="space-y-1">
            {pinnedFiltered.length > 0 && (
              <div className="px-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                All sessions
              </div>
            )}
            {normalFiltered.map(renderSession)}
          </div>
        )}
      </div>
    </aside>
  );
}
