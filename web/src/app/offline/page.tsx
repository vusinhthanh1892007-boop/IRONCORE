"use client";

import * as React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { clearOfflineQueue, getQueuedMessages } from "@/lib/offline-queue";

export default function OfflinePage() {
  const [messages, setMessages] = React.useState(getQueuedMessages());

  const handleRetry = () => {
    if (typeof window !== "undefined") {
      window.location.href = "/chat";
    }
  };

  const handleClear = () => {
    clearOfflineQueue();
    setMessages([]);
  };

  return (
    <div className="min-h-[100dvh] bg-zinc-50">
      <div className="mx-auto flex min-h-[100dvh] max-w-2xl flex-col gap-6 px-6 py-16">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-zinc-400">Offline</p>
          <h1 className="mt-3 text-3xl font-semibold text-zinc-900">You&apos;re offline</h1>
          <p className="mt-2 text-sm text-zinc-500">
            IronCore cached this page. Check your connection and retry.
          </p>
        </div>

        <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
          <div className="text-sm font-semibold text-zinc-900">Queued messages</div>
          <div className="mt-4 space-y-3 text-sm text-zinc-600">
            {messages.length ? (
              messages.map((message) => (
                <div
                  key={message.id}
                  className="rounded-xl border border-zinc-100 bg-zinc-50 px-4 py-3"
                >
                  <div className="text-xs text-zinc-400">Session {message.sessionId}</div>
                  <div className="mt-2 text-sm text-zinc-700">{message.content}</div>
                  <div className="mt-2 text-[11px] text-zinc-400">
                    {new Date(message.createdAt).toLocaleString()}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-zinc-400">No queued messages.</div>
            )}
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={handleRetry} className="rounded-full">
              Retry Connection
            </Button>
            <Button variant="outline" onClick={handleClear} className="rounded-full">
              Clear Queue
            </Button>
            <Button asChild variant="ghost" className="rounded-full">
              <Link href="/chat">Back to Chat</Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
