"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { InputBar } from "@/components/chat/InputBar";
import { MessageList } from "@/components/chat/MessageList";
import { streamChat } from "@/lib/sse-client";
import { createMessage, useChatStore, type Attachment } from "@/store/chat-store";
import { Cloud, ArrowCounterClockwise as RotateCcw, ShieldCheck, WifiHigh as Wifi } from "@phosphor-icons/react";
import { Activity, Database, Coins } from "lucide-react";
import { useSession } from "next-auth/react";
import { queueOfflineMessage } from "@/lib/offline-queue";
import { usePullToRefresh } from "@/hooks/usePullToRefresh";
import { useRouter } from "next/navigation";
import { IronManPanel } from "@/components/ironman/IronManPanel";
import type { GestureKey, IronManAction } from "@/lib/ironman-settings";
import {
  defaultUserSettings,
  readUserSettings,
  USER_SETTINGS_EVENT,
  type UserSettings,
} from "@/lib/user-settings";

const SYSTEM_SEED = {
  title: "The Engine",
  meta: "Ready",
  content:
    "Engine core online. Local workspace ready. Type a command or ask a question to begin.",
};

export function ChatWindow() {
  const router = useRouter();
  const {
    sessions,
    activeSessionId,
    createSession,
    addMessage,
    appendToken,
    finalizeMessage,
    setStreaming,
    setModel,
    getActiveMessages,
    isStreaming,
    currentModel,
    setToolBadge,
  } = useChatStore();

  const [input, setInput] = React.useState("");
  const [attachments, setAttachments] = React.useState<Attachment[]>([]);
  const [files, setFiles] = React.useState<File[]>([]);
  const [streamStatus, setStreamStatus] = React.useState<string | null>(null);
  const [streamLogs, setStreamLogs] = React.useState<Array<{ id: string; label: string }>>(
    []
  );
  const [viewportHeight, setViewportHeight] = React.useState<number | null>(null);
  const [isOnline, setIsOnline] = React.useState(true);
  const [provider, setProvider] = React.useState(defaultUserSettings.apiProvider);
  const [models, setModels] = React.useState<string[]>([defaultUserSettings.defaultModel]);
  const abortRef = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const { data: session } = useSession();
  const apiKey = session?.apiKey ?? "";

  React.useEffect(() => {
    if (!activeSessionId && sessions.length === 0) {
      const seed = createMessage({
        role: "assistant",
        content: SYSTEM_SEED.content,
        title: SYSTEM_SEED.title,
        meta: SYSTEM_SEED.meta,
      });
      createSession(undefined, seed);
    }
  }, [activeSessionId, sessions.length, createSession]);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    setIsOnline(window.navigator.onLine);
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const applyUserSettings = React.useCallback(async (next: UserSettings) => {
    const nextProvider = next.apiProvider || defaultUserSettings.apiProvider;
    const preferredModel = next.defaultModel || defaultUserSettings.defaultModel;
    setProvider(nextProvider);

    if (["ollama", "localai", "vllm", "lmstudio"].includes(nextProvider)) {
      try {
        const res = await fetch(`/api/models?provider=${encodeURIComponent(nextProvider)}`, { cache: "no-store" });
        const payload = (await res.json()) as {
          models?: Array<{ model_id?: string }>;
        };
        const fetched = (payload.models ?? [])
          .map((item) => String(item.model_id ?? "").trim())
          .filter(Boolean);
        const nextModels = fetched.length ? fetched : [preferredModel];
        setModels(nextModels);
        setModel(nextModels.includes(preferredModel) ? preferredModel : nextModels[0]);
        return;
      } catch {
        // fall through to local stored preference
      }
    }

    setModels([preferredModel]);
    setModel(preferredModel);
  }, [setModel]);

  React.useEffect(() => {
    void applyUserSettings(readUserSettings());

    const listener = (event: Event) => {
      const detail = (event as CustomEvent<UserSettings>).detail;
      if (!detail) return;
      void applyUserSettings(detail);
    };

    window.addEventListener(USER_SETTINGS_EVENT, listener as EventListener);
    return () => {
      window.removeEventListener(USER_SETTINGS_EVENT, listener as EventListener);
    };
  }, [applyUserSettings]);

  React.useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [viewportHeight]);

  const messages = getActiveMessages();
  const activeSession = activeSessionId ?? sessions[0]?.id;
  const sessionLabel = activeSession ? activeSession.slice(0, 6) : "----";

  // Calculate live telemetry metrics (exclude system seed and error banners)
  const inTokens = React.useMemo(() => {
    return Math.floor(
      messages
        .filter((m) => m.role === "user")
        .reduce((acc, m) => acc + m.content.length, 0) / 4
    );
  }, [messages]);

  const outTokens = React.useMemo(() => {
    return Math.floor(
      messages
        .filter(
          (m) =>
            m.role === "assistant" &&
            m.content !== SYSTEM_SEED.content &&
            !m.content.startsWith('{"error"')
        )
        .reduce((acc, m) => acc + m.content.length, 0) / 4
    );
  }, [messages]);

  const contextLimit = currentModel.includes("5.3") ? 200000 : currentModel.includes("claude") ? 200000 : 128000;
  const contextPct = inTokens + outTokens === 0 ? "0.0" : Math.min(((inTokens + outTokens) / contextLimit) * 100, 100).toFixed(1);
  const isLocalProvider = ["ollama", "localai", "vllm", "lmstudio"].includes(provider.toLowerCase());
  const estCost = isLocalProvider
    ? "0.0000"
    : ((inTokens * 0.005) / 1000 + (outTokens * 0.015) / 1000).toFixed(4);

  const pushLog = React.useCallback((label: string) => {
    setStreamLogs((prev) => {
      const next = [{ id: `${Date.now()}-${label}`, label }, ...prev];
      return next.slice(0, 6);
    });
  }, []);

  const formatToolLabel = React.useCallback(
    (name: string) =>
      name
        .split(/[_-]/)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" "),
    []
  );

  const notifyCompletion = React.useCallback((label: string) => {
    if (typeof window === "undefined") return;
    if (!document.hidden) return;
    if (!("Notification" in window)) return;
    if (Notification.permission === "default") {
      Notification.requestPermission().catch(() => null);
      return;
    }
    if (Notification.permission !== "granted") return;
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.ready
        .then((registration) =>
          registration.showNotification("The Engine", {
            body: label,
            icon: "/icon-192.png",
          })
        )
        .catch(() => null);
      return;
    }
    new Notification("The Engine", { body: label, icon: "/icon-192.png" });
  }, []);

  usePullToRefresh({
    enabled: !isStreaming,
    onRefresh: () => window.location.reload(),
    getScrollElement: () => scrollRef.current,
  });

  const handleAddFiles = (fileList: File[]) => {
    const maxSize = 10 * 1024 * 1024;
    const remainingSlots = Math.max(5 - attachments.length, 0);
    const incoming = Array.from(fileList)
      .filter((file) => file.size <= maxSize)
      .slice(0, remainingSlots);

    if (incoming.length !== fileList.length) {
      setStreamStatus("Some files exceeded 10MB and were skipped.");
    }
    setFiles((prev) => [...prev, ...incoming]);
    setAttachments((prev) => [
      ...prev,
      ...incoming.map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}`,
        name: file.name,
        type: file.type,
        size: file.size,
        previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined,
      })),
    ]);
  };

  const handleRemoveFile = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((file) => file.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((file) => file.id !== id);
    });
    setFiles((prev) =>
      prev.filter((file) => `${file.name}-${file.size}-${file.lastModified}` !== id)
    );
  };

  const handleSend = React.useCallback(async (overrideMessage?: string) => {
    if (isStreaming) return;
    if (!activeSession) return;

    const content = (overrideMessage ?? input).trim();
    if (!content && files.length === 0) return;

    if (typeof window !== "undefined" && !navigator.onLine) {
      const offlineMessage = createMessage({
        role: "user",
        content: content || "(attachments)",
        title: "You",
        meta: "Queued (offline)",
      });
      addMessage(activeSession, offlineMessage);
      queueOfflineMessage({
        id: offlineMessage.id,
        sessionId: activeSession,
        content: content || "(attachments)",
        createdAt: new Date().toISOString(),
      });
      setInput("");
      attachments.forEach((file) => file.previewUrl && URL.revokeObjectURL(file.previewUrl));
      setAttachments([]);
      setFiles([]);
      const attachmentNote = files.length ? " Attachments are not queued." : "";
      setStreamStatus(`You're offline. Message queued for later.${attachmentNote}`);
      pushLog("Queued offline.");
      return;
    }

    const userMessage = createMessage({
      role: "user",
      content: content || "(attachments)",
      title: "You",
    });
    addMessage(activeSession, userMessage);

    const assistantMessage = createMessage({
      role: "assistant",
      content: "",
      isStreaming: true,
      title: "The Engine",
    });
    addMessage(activeSession, assistantMessage);

    setInput("");
    attachments.forEach((file) => file.previewUrl && URL.revokeObjectURL(file.previewUrl));
    setAttachments([]);
    setFiles([]);
    setStreamStatus(null);
    setStreaming(true);
    pushLog("RAG Searching...");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const chunk of streamChat({
        sessionId: activeSession,
        message: content,
        apiKey: apiKey || undefined,
        files,
        model: currentModel,
        provider,
        history: messages
          .filter((message) => message.role === "user" || message.role === "assistant" || message.role === "system")
          .map((message) => ({ role: message.role, content: message.content })),
        signal: controller.signal,
      })) {
        if (chunk.type === "token" && chunk.content) {
          appendToken(activeSession, assistantMessage.id, chunk.content);
        }

        if (chunk.type === "tool_start" && chunk.tool_name) {
          const label = formatToolLabel(chunk.tool_name);
          setToolBadge(activeSession, assistantMessage.id, label, "running");
          pushLog(`${label} running...`);
        }

        if (chunk.type === "tool_end" && chunk.tool_name) {
          const label = formatToolLabel(chunk.tool_name);
          setToolBadge(activeSession, assistantMessage.id, label, "done");
          pushLog(`${label} done.`);
        }

        if (chunk.type === "error") {
          finalizeMessage(activeSession, assistantMessage.id, {
            content: chunk.error ?? "Stream error.",
          });
          setStreamStatus(chunk.error ?? "Stream error.");
          pushLog("Stream error.");
        }

        if (chunk.type === "done") {
          finalizeMessage(activeSession, assistantMessage.id, {
            cached: chunk.cached,
            tokens_used: chunk.tokens_used,
            cache_similarity: chunk.cache_similarity,
          });
          pushLog("Streaming complete.");
          notifyCompletion("Response ready.");
        }
      }
    } catch (error) {
      const fallbackMessage =
        error instanceof Error && error.message.toLowerCase().includes("failed to fetch")
          ? "Network error: cannot reach /api/chat/stream. Check web server status and retry."
          : error instanceof Error && error.message.toLowerCase().includes("network error")
            ? "Network error: cannot reach /api/chat/stream. Check web server status and retry."
            : "Stream cancelled.";
      finalizeMessage(activeSession, assistantMessage.id, {
        content: error instanceof Error ? fallbackMessage : "Stream cancelled.",
      });
      pushLog("Stream cancelled.");
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [
    isStreaming,
    activeSession,
    input,
    files,
    attachments,
    apiKey,
    currentModel,
    addMessage,
    appendToken,
    finalizeMessage,
    setStreaming,
    setToolBadge,
    notifyCompletion,
    pushLog,
    formatToolLabel,
    messages,
    provider,
  ]);

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const updateViewport = () => {
      const height = window.visualViewport?.height ?? window.innerHeight;
      setViewportHeight(height);
    };
    updateViewport();
    window.visualViewport?.addEventListener("resize", updateViewport);
    window.addEventListener("resize", updateViewport);

    const handleRunScript = (e: CustomEvent<string>) => {
      if (!e.detail) return;
      setTimeout(() => {
        void handleSend(e.detail);
      }, 50);
    };

    window.addEventListener("engine-run-script", handleRunScript as EventListener);
    return () => {
      window.visualViewport?.removeEventListener("resize", updateViewport);
      window.removeEventListener("resize", updateViewport);
      window.removeEventListener("engine-run-script", handleRunScript as EventListener);
    };
  }, [handleSend]);

  const handleStop = React.useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, [setStreaming]);

  const handleClearInput = React.useCallback(() => {
    setInput("");
  }, []);

  const handleNewSessionFromGesture = React.useCallback(() => {
    const seed = createMessage({
      role: "assistant",
      content: SYSTEM_SEED.content,
      title: SYSTEM_SEED.title,
      meta: "New session",
    });
    createSession(undefined, seed);
    setInput("");
  }, [createSession]);

  const handleIronManAction = React.useCallback(
    (action: IronManAction, gesture: GestureKey) => {
      if (action === "none") return;

      if (action === "stop_stream") {
        handleStop();
        setStreamStatus(`Gesture ${gesture}: stream stopped.`);
        return;
      }

      if (action === "clear_input") {
        handleClearInput();
        setStreamStatus(`Gesture ${gesture}: input cleared.`);
        return;
      }

      if (action === "new_session") {
        handleNewSessionFromGesture();
        setStreamStatus(`Gesture ${gesture}: new session created.`);
        return;
      }

      if (action === "submit_input") {
        void handleSend();
        setStreamStatus(`Gesture ${gesture}: input submitted.`);
        return;
      }

      if (action === "approve_hitl") {
        router.push("/hitl");
        setStreamStatus(`Gesture ${gesture}: open HITL approval.`);
      }
    },
    [handleClearInput, handleNewSessionFromGesture, handleSend, handleStop, router]
  );

  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!event.ctrlKey || !event.shiftKey) return;
      const k = event.key;
      if (!["1", "2", "3", "4", "5"].includes(k)) return;
      event.preventDefault();

      const map: Record<string, { action: IronManAction; gesture: GestureKey }> = {
        "1": { action: "approve_hitl", gesture: "thumbs_up" },
        "2": { action: "stop_stream", gesture: "fist" },
        "3": { action: "clear_input", gesture: "open_hand" },
        "4": { action: "new_session", gesture: "peace" },
        "5": { action: "submit_input", gesture: "point_up" },
      };

      const picked = map[k];
      handleIronManAction(picked.action, picked.gesture);
    };

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, [handleIronManAction]);

  const lastUserMessage = [...messages].reverse().find((msg) => msg.role === "user");

  return (
    <div
      className="relative flex min-h-[100dvh] flex-col gap-6"
      style={viewportHeight ? { height: viewportHeight } : undefined}
    >
      <div className="flex items-center justify-between border-b border-border pb-3 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>Workspace</span>
          <span>/</span>
          <span>The Engine</span>
          <span>/</span>
          <span className="text-foreground font-medium">Session #{sessionLabel}</span>
        </div>
        <div className="flex items-center gap-3">
          <Wifi className={`h-4 w-4 ${isOnline ? "text-emerald-500" : "text-muted-foreground"}`} />
          <Cloud className="h-4 w-4 text-amber-500" />
          <ShieldCheck className="h-4 w-4 text-emerald-500" />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="h-7 px-2 text-xs">
                {currentModel}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {models.map((model) => (
                <DropdownMenuItem key={model} onSelect={() => setModel(model)}>
                  {model}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {streamStatus ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2 text-xs text-destructive dark:text-red-400">
          {streamStatus}
        </div>
      ) : null}
      {provider !== "ollama" && !apiKey ? (
        <div className="rounded-lg border border-border bg-muted px-4 py-2 text-xs text-foreground">
          Missing API key. Set it in{" "}
          <a href="/settings" className="underline underline-offset-2">Settings</a>
          {" "}to enable authenticated tool calls.
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col relative">
        <MessageList
          messages={messages}
          isStreaming={isStreaming}
          scrollRef={scrollRef}
        />

        {/* Real-time Telemetry Overlay */}
        <div className="md:absolute top-2 right-4 flex items-center gap-4 rounded-full border border-border bg-background/80 px-4 py-1.5 text-[10px] font-mono text-muted-foreground shadow-sm backdrop-blur-md">
          <div className="flex items-center gap-1.5 tooltip-trigger">
            <Database className="h-3 w-3 text-emerald-500" />
            <span>Ctx: {contextPct}%</span>
          </div>
          <div className="h-3 w-[1px] bg-border" />
          <div className="flex items-center gap-1.5">
            <Activity className="h-3 w-3 text-blue-500" />
            <span>In {inTokens} | Out {outTokens}</span>
          </div>
          <div className="h-3 w-[1px] bg-border" />
          <div className="flex items-center gap-1.5">
            <Coins className="h-3 w-3 text-amber-500" />
            <span>{isLocalProvider ? "Local (Free)" : `Est $${estCost}`}</span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div>Press Enter or Cmd/Ctrl+Enter to send, Shift+Enter for a new line.</div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="gap-2 text-xs"
          disabled={!lastUserMessage || isStreaming}
          onClick={() => lastUserMessage && handleSend(lastUserMessage.content)}
        >
          <RotateCcw className="h-4 w-4" />
          Regenerate
        </Button>
      </div>

      <div className="sticky bottom-0 z-10 bg-background/95 pb-2 pt-3 md:static md:bg-transparent">
        <InputBar
          value={input}
          onChange={setInput}
          onSend={() => handleSend()}
          onStop={handleStop}
          isStreaming={isStreaming}
          attachments={attachments}
          onAddFiles={handleAddFiles}
          onRemoveFile={handleRemoveFile}
        />
      </div>

      {streamLogs.length ? (
        <div className="absolute bottom-24 right-4 w-72 rounded-xl border border-border bg-card/90 p-3 text-xs text-muted-foreground shadow-sm md:bottom-6 md:right-6">
          <div className="space-y-1">
            {streamLogs.map((log) => (
              <div key={log.id} className="flex items-center gap-2">
                <span className="text-emerald-500">*</span>
                <span>{log.label}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <IronManPanel onGestureAction={handleIronManAction} />
    </div>
  );
}
