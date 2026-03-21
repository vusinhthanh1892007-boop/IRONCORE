"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Check, Copy, CircleNotch as Loader2 } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import type { Message } from "@/store/chat-store";

interface MessageBubbleProps {
  message: Message;
}

function CodeBlock({
  inline,
  className,
  children,
}: {
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
}) {
  const [copied, setCopied] = React.useState(false);
  const code = String(children ?? "").replace(/\n$/, "");

  if (inline) {
    return (
      <code className="rounded bg-muted px-1 py-0.5 text-xs text-foreground">
        {children}
      </code>
    );
  }

  const language = className?.replace("language-", "") ?? "";

  return (
    <div className="group relative mt-3">
      <div className="absolute right-3 top-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        {language ? <span>{language}</span> : null}
        <button
          type="button"
          className="flex h-6 w-6 items-center justify-center rounded-md border border-border bg-card"
          onClick={async () => {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      <pre className="rounded-lg border border-border bg-muted p-3">
        <code className={className}>{code}</code>
      </pre>
    </div>
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const time = new Date(message.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="flex items-start gap-3">
      <div
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-lg text-xs font-semibold",
          isUser ? "bg-muted text-muted-foreground" : "bg-foreground text-background"
        )}
      >
        {isUser ? "U" : "E"}
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">
            {message.title ?? (isUser ? "You" : "The Engine")}
          </span>
          {message.meta ? <span>{message.meta}</span> : null}
          {message.cached ? (
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-600">
              Cached
            </span>
          ) : null}
          <span className="ml-auto">{time}</span>
        </div>

        {message.toolBadges && message.toolBadges.length ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {message.toolBadges.map((badge) => (
              <div
                key={badge.id}
                className="flex items-center gap-2 rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground"
              >
                {badge.status === "running" ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Check className="h-3 w-3 text-emerald-500" />
                )}
                {badge.label}
              </div>
            ))}
          </div>
        ) : null}

        {message.attachments && message.attachments.length ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {message.attachments.map((file) => (
              <div
                key={file.id}
                className="flex items-center gap-2 rounded-md border border-border bg-card px-2 py-1 text-xs text-muted-foreground"
              >
                <span>{file.name}</span>
                <span>{Math.round(file.size / 1024)}kb</span>
              </div>
            ))}
          </div>
        ) : null}

        {message.content ? (
          <div className="markdown mt-2 text-sm text-foreground">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                code: ({ className, children, ...props }) => (
                  <CodeBlock className={className} {...props}>
                    {children}
                  </CodeBlock>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {message.isStreaming ? <span className="typing-cursor" /> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
