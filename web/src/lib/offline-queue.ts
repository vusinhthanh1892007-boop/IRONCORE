export interface OfflineQueuedMessage {
  id: string;
  sessionId: string;
  content: string;
  createdAt: string;
}

const STORAGE_KEY = "ironcore.offline.queue";

export function getQueuedMessages(): OfflineQueuedMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as OfflineQueuedMessage[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function queueOfflineMessage(message: OfflineQueuedMessage) {
  if (typeof window === "undefined") return;
  const current = getQueuedMessages();
  const next = [message, ...current].slice(0, 50);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

export function clearOfflineQueue() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}
