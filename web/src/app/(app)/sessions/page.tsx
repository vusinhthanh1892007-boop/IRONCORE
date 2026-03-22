"use client";

import * as React from "react";
import { useChatStore } from "@/store/chat-store";
import { ChatCircle as MessageCircle, PushPin as Pin, Trash as Trash2 } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

export default function SessionsPage() {
  const { sessions, activeSessionId, switchSession, deleteSession, togglePinSession } =
    useChatStore();

  const pinned = sessions.filter((s) => s.pinned);
  const normal = sessions.filter((s) => !s.pinned);

  const renderRow = (session: (typeof sessions)[number]) => (
    <div
      key={session.id}
      className={cn(
        "flex items-center gap-3 rounded-xl border px-4 py-3 transition",
        session.id === activeSessionId
          ? "border-primary/40 bg-primary/5"
          : "border-border bg-card hover:bg-accent/40"
      )}
    >
      <MessageCircle className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
      <button
        type="button"
        className="min-w-0 flex-1 text-left"
        onClick={() => switchSession(session.id)}
      >
        <div className="flex items-center gap-1.5 text-sm font-medium">
          {session.pinned && <Pin className="h-3 w-3 fill-amber-400 text-amber-500" />}
          <span className="truncate">{session.name}</span>
        </div>
        <div className="text-xs text-muted-foreground">
          Created {new Date(session.createdAt).toLocaleString()} ·{" "}
          Updated {new Date(session.updatedAt).toLocaleString()}
        </div>
      </button>
      <button
        type="button"
        title={session.pinned ? "Unpin" : "Pin"}
        onClick={() => togglePinSession(session.id)}
        className={cn(
          "rounded p-1.5 transition",
          session.pinned
            ? "text-amber-500 hover:text-amber-600"
            : "text-muted-foreground/40 hover:text-foreground"
        )}
      >
        <Pin className={cn("h-4 w-4", session.pinned && "fill-amber-400")} />
      </button>
      <button
        type="button"
        title="Delete"
        onClick={() => deleteSession(session.id)}
        className="rounded p-1.5 text-muted-foreground/40 transition hover:text-destructive"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Sessions History</h1>
        <p className="text-sm text-muted-foreground">All chat sessions — pinned and recent.</p>
      </div>

      {sessions.length === 0 && (
        <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          No sessions yet. Start a chat to create one.
        </div>
      )}

      {pinned.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Pinned
          </div>
          {pinned.map(renderRow)}
        </div>
      )}

      {normal.length > 0 && (
        <div className="space-y-2">
          {pinned.length > 0 && (
            <div className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              All sessions
            </div>
          )}
          {normal.map(renderRow)}
        </div>
      )}
    </div>
  );
}
