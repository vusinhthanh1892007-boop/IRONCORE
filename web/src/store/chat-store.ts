import { create } from "zustand";

export interface Attachment {
  id: string;
  name: string;
  type: string;
  size: number;
  previewUrl?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  title?: string;
  meta?: string;
  isStreaming?: boolean;
  cached?: boolean;
  tokens_used?: number;
  cache_similarity?: number;
  attachments?: Attachment[];
  toolBadges?: Array<{ id: string; label: string; status: "running" | "done" }>;
}

export interface Session {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
  pinned?: boolean;
}

interface ChatState {
  sessions: Session[];
  activeSessionId: string | null;
  messagesBySession: Record<string, Message[]>;
  isStreaming: boolean;
  currentModel: string;

  createSession: (name?: string, seedMessage?: Message) => Session;
  switchSession: (id: string) => void;
  renameSession: (id: string, name: string) => void;
  deleteSession: (id: string) => void;
  togglePinSession: (id: string) => void;
  addMessage: (sessionId: string, message: Message) => void;
  appendToken: (sessionId: string, messageId: string, token: string) => void;
  finalizeMessage: (sessionId: string, messageId: string, meta: Partial<Message>) => void;
  setToolBadge: (
    sessionId: string,
    messageId: string,
    label: string,
    status: "running" | "done"
  ) => void;
  setStreaming: (value: boolean) => void;
  setModel: (model: string) => void;
  getActiveMessages: () => Message[];
}

const createId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messagesBySession: {},
  isStreaming: false,
  currentModel: "qwen2.5:7b",

  createSession: (name, seedMessage) => {
    const session: Session = {
      id: createId(),
      name: name ?? `Session ${get().sessions.length + 1}`,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };

    set((state) => ({
      sessions: [session, ...state.sessions],
      activeSessionId: session.id,
      messagesBySession: {
        ...state.messagesBySession,
        [session.id]: seedMessage ? [seedMessage] : [],
      },
    }));

    return session;
  },

  switchSession: (id) => set({ activeSessionId: id }),

  renameSession: (id, name) =>
    set((state) => ({
      sessions: state.sessions.map((session) =>
        session.id === id
          ? { ...session, name, updatedAt: Date.now() }
          : session
      ),
    })),

  togglePinSession: (id) =>
    set((state) => ({
      sessions: state.sessions.map((session) =>
        session.id === id
          ? { ...session, pinned: !session.pinned, updatedAt: Date.now() }
          : session
      ),
    })),

  deleteSession: (id) =>
    set((state) => {
      const nextSessions = state.sessions.filter((session) => session.id !== id);
      const nextMessages = { ...state.messagesBySession };
      delete nextMessages[id];

      return {
        sessions: nextSessions,
        activeSessionId:
          state.activeSessionId === id
            ? nextSessions[0]?.id ?? null
            : state.activeSessionId,
        messagesBySession: nextMessages,
      };
    }),

  addMessage: (sessionId, message) =>
    set((state) => ({
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: [...(state.messagesBySession[sessionId] ?? []), message],
      },
      sessions: state.sessions.map((session) =>
        session.id === sessionId
          ? { ...session, updatedAt: Date.now() }
          : session
      ),
    })),

  appendToken: (sessionId, messageId, token) =>
    set((state) => ({
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: (state.messagesBySession[sessionId] ?? []).map((message) =>
          message.id === messageId
            ? { ...message, content: message.content + token }
            : message
        ),
      },
    })),

  finalizeMessage: (sessionId, messageId, meta) =>
    set((state) => ({
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: (state.messagesBySession[sessionId] ?? []).map((message) =>
          message.id === messageId
            ? { ...message, ...meta, isStreaming: false }
            : message
        ),
      },
    })),

  setToolBadge: (sessionId, messageId, label, status) =>
    set((state) => ({
      messagesBySession: {
        ...state.messagesBySession,
        [sessionId]: (state.messagesBySession[sessionId] ?? []).map((message) => {
          if (message.id !== messageId) return message;
          const existing = message.toolBadges ?? [];
          const next = existing.some((badge) => badge.id === label)
            ? existing.map((badge) =>
                badge.id === label ? { ...badge, status } : badge
              )
            : [...existing, { id: label, label, status }];
          return { ...message, toolBadges: next };
        }),
      },
    })),

  setStreaming: (value) => set({ isStreaming: value }),
  setModel: (model) => set({ currentModel: model }),

  getActiveMessages: () => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return [];
    return get().messagesBySession[sessionId] ?? [];
  },
}));

export const createMessage = (message: Omit<Message, "id" | "timestamp">): Message => ({
  ...message,
  id: createId(),
  timestamp: Date.now(),
});
