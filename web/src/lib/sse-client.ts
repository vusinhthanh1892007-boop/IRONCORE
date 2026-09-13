export interface StreamChunk {
  type: "token" | "done" | "error" | "tool_start" | "tool_end";
  content?: string;
  session_id?: string;
  tokens_used?: number;
  cached?: boolean;
  cache_similarity?: number;
  tool_name?: string;
  error?: string;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function isRetryableNetworkError(error: unknown) {
  if (!(error instanceof Error)) return false;
  if (error.name === "AbortError") return false;
  const msg = error.message.toLowerCase();
  return msg.includes("failed to fetch") || msg.includes("networkerror");
}

async function fetchStreamWithRetry(
  url: string,
  init: RequestInit,
  retries = 1
) {
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fetch(url, init);
    } catch (error) {
      lastError = error;
      if (!isRetryableNetworkError(error) || attempt === retries) {
        throw error;
      }
      await sleep(350);
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Failed to fetch stream.");
}

interface StreamChatOptions {
  sessionId: string;
  message: string;
  apiKey?: string;
  files?: File[];
  model?: string;
  provider?: string;
  history?: Array<{ role: "user" | "assistant" | "system"; content: string }>;
  signal?: AbortSignal;
  baseUrl?: string;
  endpoint?: string;
}

const fileToBase64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result?.toString().split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

export async function* streamChat({
  sessionId,
  message,
  apiKey,
  files,
  model,
  provider,
  history,
  signal,
  baseUrl = "",
  endpoint = "/api/chat/stream",
}: StreamChatOptions): AsyncGenerator<StreamChunk> {
  const payload = {
    session_id: sessionId,
    message,
    model,
    provider,
    history,
    files: files && files.length ? await Promise.all(files.map(fileToBase64)) : undefined,
  };

  let res: Response;
  try {
    res = await fetchStreamWithRetry(`${baseUrl}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(apiKey ? { "X-IronCore-API-Key": apiKey } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    yield {
      type: "error",
      error: "Network error while connecting to chat stream.",
    };
    return;
  }

  if (!res.ok || !res.body) {
    yield {
      type: "error",
      error: `HTTP ${res.status}`,
    };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const data = trimmed.replace(/^data:\s?/, "");
      if (!data) continue;
      if (data === "[DONE]") {
        yield { type: "done" };
        continue;
      }

      try {
        const parsed = JSON.parse(data) as StreamChunk;
        yield parsed;
      } catch {
        yield {
          type: "error",
          error: "Malformed stream payload.",
        };
      }
    }
  }
}
