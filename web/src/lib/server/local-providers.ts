export type LocalProviderId = "ollama" | "localai" | "vllm" | "lmstudio";

export interface LocalProviderModel {
  id: string;
  name: string;
  family?: string;
}

export interface LocalProviderScanResult {
  id: LocalProviderId;
  label: string;
  baseUrl: string;
  available: boolean;
  models: LocalProviderModel[];
  error?: string;
}

type ProviderConfig = {
  id: LocalProviderId;
  label: string;
  envVar: string;
  defaultBaseUrl: string;
};

const PROVIDERS: ProviderConfig[] = [
  {
    id: "ollama",
    label: "Ollama",
    envVar: "IRONCORE_OLLAMA_BASE_URL",
    defaultBaseUrl: process.env.NEXT_PUBLIC_OLLAMA_BASE_URL ?? "http://127.0.0.1:11434",
  },
  {
    id: "localai",
    label: "LocalAI",
    envVar: "IRONCORE_LOCALAI_BASE_URL",
    defaultBaseUrl: process.env.NEXT_PUBLIC_LOCALAI_BASE_URL ?? "http://127.0.0.1:8080/v1",
  },
  {
    id: "vllm",
    label: "vLLM",
    envVar: "IRONCORE_VLLM_BASE_URL",
    defaultBaseUrl: process.env.NEXT_PUBLIC_VLLM_BASE_URL ?? "http://127.0.0.1:8001/v1",
  },
  {
    id: "lmstudio",
    label: "LM Studio",
    envVar: "IRONCORE_LMSTUDIO_BASE_URL",
    defaultBaseUrl: process.env.NEXT_PUBLIC_LMSTUDIO_BASE_URL ?? "http://127.0.0.1:1234/v1",
  },
];

function providerConfig(provider: LocalProviderId): ProviderConfig {
  const found = PROVIDERS.find((item) => item.id === provider);
  if (!found) {
    throw new Error(`Unsupported local provider: ${provider}`);
  }
  return found;
}

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

export function getLocalProviderBaseUrl(provider: LocalProviderId): string {
  const config = providerConfig(provider);
  const configured = process.env[config.envVar];
  const raw = (configured && configured.trim()) || config.defaultBaseUrl;
  return normalizeBaseUrl(raw);
}

async function scanOllama(baseUrl: string, id: LocalProviderId, label: string): Promise<LocalProviderScanResult> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    const res = await fetch(`${baseUrl}/api/tags`, {
      cache: "no-store",
      signal: controller.signal,
    }).finally(() => clearTimeout(timeout));
    if (!res.ok) {
      return { id, label, baseUrl, available: false, models: [], error: `HTTP ${res.status}` };
    }

    const payload = (await res.json()) as {
      models?: Array<{ name?: string; model?: string; details?: { family?: string } }>;
    };

    const models: LocalProviderModel[] = [];
    for (const row of payload.models ?? []) {
      const modelId = String(row.name ?? row.model ?? "").trim();
      if (!modelId) continue;
      models.push({
        id: modelId,
        name: modelId,
        family: row.details?.family,
      });
    }

    return {
      id,
      label,
      baseUrl,
      available: true,
      models,
    };
  } catch (error) {
    return {
      id,
      label,
      baseUrl,
      available: false,
      models: [],
      error: error instanceof Error ? error.message : "Unavailable",
    };
  }
}

async function scanOpenAiCompatible(
  baseUrl: string,
  id: Exclude<LocalProviderId, "ollama">,
  label: string
): Promise<LocalProviderScanResult> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    const res = await fetch(`${baseUrl}/models`, {
      cache: "no-store",
      signal: controller.signal,
    }).finally(() => clearTimeout(timeout));
    if (!res.ok) {
      return { id, label, baseUrl, available: false, models: [], error: `HTTP ${res.status}` };
    }

    const payload = (await res.json()) as {
      data?: Array<{ id?: string; name?: string; owned_by?: string }>;
    };

    const models: LocalProviderModel[] = [];
    for (const row of payload.data ?? []) {
      const modelId = String(row.id ?? row.name ?? "").trim();
      if (!modelId) continue;
      models.push({
        id: modelId,
        name: String(row.name ?? modelId).trim() || modelId,
        family: row.owned_by,
      });
    }

    return {
      id,
      label,
      baseUrl,
      available: true,
      models,
    };
  } catch (error) {
    return {
      id,
      label,
      baseUrl,
      available: false,
      models: [],
      error: error instanceof Error ? error.message : "Unavailable",
    };
  }
}

export async function listLocalProviderModels(provider: LocalProviderId): Promise<LocalProviderScanResult> {
  const config = providerConfig(provider);
  const baseUrl = getLocalProviderBaseUrl(provider);

  if (provider === "ollama") {
    return scanOllama(baseUrl, provider, config.label);
  }

  return scanOpenAiCompatible(baseUrl, provider, config.label);
}

export async function listAllLocalProviderModels(): Promise<LocalProviderScanResult[]> {
  const providers: LocalProviderId[] = ["ollama", "localai", "vllm", "lmstudio"];
  return Promise.all(providers.map((provider) => listLocalProviderModels(provider)));
}
