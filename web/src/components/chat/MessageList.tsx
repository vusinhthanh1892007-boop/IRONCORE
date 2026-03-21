"use client";

import * as React from "react";
import type { Message } from "@/store/chat-store";
import { MessageBubble } from "@/components/chat/MessageBubble";

interface MessageListProps {
  messages: Message[];
  isStreaming: boolean;
  scrollRef?: React.RefObject<HTMLDivElement | null>;
}

export function MessageList({ messages, isStreaming, scrollRef }: MessageListProps) {
  const endRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isStreaming]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 space-y-6 overflow-y-auto overscroll-contain pb-24 md:pb-4"
    >
      {messages.length === 0 ? (
        <div className="rounded-lg border border-dashed border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-500">
          Start a conversation to see streaming responses.
        </div>
      ) : null}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <div ref={endRef} />
    </div>
  );
}
