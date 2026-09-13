const DEFAULT_OLLAMA_BASE_URL =
  process.env.IRONCORE_OLLAMA_BASE_URL ??
  process.env.NEXT_PUBLIC_OLLAMA_BASE_URL ??
  "http://127.0.0.1:11434";

export interface OllamaModelInfo {
  name: string;
  model: string;
  digest?: string;
  parameterSize?: string;
  family?: string;
}

export interface OllamaMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export class OllamaError extends Error {}

async function fetchOllama(path: string, init?: RequestInit) {
  const controller = new AbortController();
  const timeoutMs = path === "/api/chat" ? 60000 : 8000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${DEFAULT_OLLAMA_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
      signal: init?.signal ?? controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new OllamaError("Ollama request timed out. Please check local Ollama runtime.");
    }
    throw new OllamaError(
      error instanceof Error ? error.message : "Cannot connect to local Ollama runtime."
    );
  } finally {
    clearTimeout(timeout);
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let errMsg = text || `Ollama HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(text) as { error?: string };
      if (parsed && typeof parsed.error === "string") {
        errMsg = parsed.error;
      }
    } catch {
      // keep raw text
    }
    throw new OllamaError(errMsg);
  }

  return res;
}

export function isEmbeddingModel(name: string, capabilities?: string[], family?: string): boolean {
  if (Array.isArray(capabilities) && capabilities.length > 0) {
    const hasChat = capabilities.some((c) =>
      ["completion", "chat", "tools", "vision"].includes(c.toLowerCase())
    );
    if (!hasChat && capabilities.includes("embedding")) {
      return true;
    }
  }

  const n = name.toLowerCase();
  const f = (family ?? "").toLowerCase();

  return (
    n.includes("bge-") ||
    n.includes("bge_") ||
    n.includes("embed") ||
    n.includes("minilm") ||
    n.includes("paraphrase") ||
    n.includes("gte-") ||
    n.includes("e5-") ||
    n.includes("snowflake-arctic") ||
    n.includes("rerank") ||
    f === "bert" ||
    f === "nomic-bert"
  );
}

export async function listOllamaModels(): Promise<OllamaModelInfo[]> {
  const res = await fetchOllama("/api/tags");
  const payload = (await res.json()) as {
    models?: Array<{
      name?: string;
      model?: string;
      digest?: string;
      details?: { parameter_size?: string; family?: string };
      capabilities?: string[];
    }>;
  };

  const models: OllamaModelInfo[] = [];
  for (const row of payload.models ?? []) {
    const name = row.name ?? row.model ?? "";
    if (!name) continue;
    if (isEmbeddingModel(name, row.capabilities, row.details?.family)) {
      continue;
    }
    models.push({
      name,
      model: row.model ?? name,
      digest: row.digest,
      parameterSize: row.details?.parameter_size,
      family: row.details?.family,
    });
  }
  return models;
}

export async function resolveOllamaModel(requested?: string | null): Promise<string> {
  const models = await listOllamaModels();
  if (!models.length) {
    throw new OllamaError(
      "No chat models found in Ollama (embedding models do not support chat). Please run: ollama pull qwen2.5:3b or ollama pull llama3"
    );
  }

  const needle = requested?.trim().toLowerCase();
  if (needle) {
    const exact = models.find((model) => model.name.toLowerCase() === needle);
    if (exact) return exact.name;

    const partial = models.find((model) => model.name.toLowerCase().includes(needle));
    if (partial) return partial.name;
  }

  return models[0].name;
}

export async function requestOllamaChat(
  model: string,
  messages: OllamaMessage[],
  options?: {
    stream?: boolean;
    format?: "json";
  }
) {
  return fetchOllama("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      model,
      messages,
      stream: options?.stream ?? false,
      ...(options?.format ? { format: options.format } : {}),
    }),
  });
}

export function getOllamaBaseUrl() {
  return DEFAULT_OLLAMA_BASE_URL;
}
