"use client";

import * as React from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Card } from "@/components/ui/card";
import {
  defaultIronManSettings,
  getIronManSettings,
  saveIronManSettings,
  type GestureKey,
  type IronManAction,
  type IronManSettings,
} from "@/lib/ironman-settings";
import {
  defaultUserSettings,
  readUserSettings,
  writeUserSettings,
  type UserSettings,
} from "@/lib/user-settings";

const maskKey = (key: string) => {
  if (key.length <= 6) return key;
  return `${key.slice(0, 2)}-****-****-${key.slice(-4)}`;
};

const formatUtcDateTime = (epochSeconds: number | null) => {
  if (!epochSeconds) return "never";
  const iso = new Date(epochSeconds * 1000).toISOString();
  return `${iso.slice(0, 19).replace("T", " ")} UTC`;
};

const GOOGLE_MAPS_KEY_RE = /^AIza[0-9A-Za-z_-]{20,}$/;

type TokenProfile = {
  profile_id: string;
  environment: string;
  scopes: string[];
  expires_at: number | null;
  last_used_at: number | null;
  revoked: boolean;
  expired: boolean;
  expiring_soon: boolean;
  has_token: boolean;
};

const defaultSettings: UserSettings = defaultUserSettings;

const TIMEZONES = [
  { value: "Etc/GMT+12", label: "UTC−12:00 — Baker Island" },
  { value: "Pacific/Pago_Pago", label: "UTC−11:00 — Pago Pago, American Samoa" },
  { value: "Pacific/Honolulu", label: "UTC−10:00 — Honolulu (Hawaii, USA)" },
  { value: "America/Anchorage", label: "UTC−09:00 — Anchorage (Alaska, USA)" },
  { value: "America/Los_Angeles", label: "UTC−08:00 — Los Angeles, Seattle (USA)" },
  { value: "America/Denver", label: "UTC−07:00 — Denver (USA)" },
  { value: "America/Phoenix", label: "UTC−07:00 — Phoenix (USA, no DST)" },
  { value: "America/Chicago", label: "UTC−06:00 — Chicago, Mexico City" },
  { value: "America/New_York", label: "UTC−05:00 — New York, Toronto" },
  { value: "America/Bogota", label: "UTC−05:00 — Bogotá (Colombia)" },
  { value: "America/Lima", label: "UTC−05:00 — Lima (Peru)" },
  { value: "America/Caracas", label: "UTC−04:00 — Caracas (Venezuela)" },
  { value: "America/Santiago", label: "UTC−04:00 — Santiago (Chile)" },
  { value: "America/Halifax", label: "UTC−04:00 — Halifax (Canada)" },
  { value: "America/Sao_Paulo", label: "UTC−03:00 — São Paulo, Rio de Janeiro" },
  { value: "America/Argentina/Buenos_Aires", label: "UTC−03:00 — Buenos Aires (Argentina)" },
  { value: "Atlantic/Azores", label: "UTC−01:00 — Azores (Portugal)" },
  { value: "UTC", label: "UTC+00:00 — UTC / Reykjavik" },
  { value: "Europe/London", label: "UTC+00:00 — London, Dublin, Lisbon" },
  { value: "Europe/Paris", label: "UTC+01:00 — Paris, Berlin, Rome, Madrid" },
  { value: "Africa/Lagos", label: "UTC+01:00 — Lagos, Luanda, Kinshasa" },
  { value: "Africa/Cairo", label: "UTC+02:00 — Cairo (Egypt), Johannesburg" },
  { value: "Europe/Helsinki", label: "UTC+02:00 — Helsinki, Kyiv, Bucharest" },
  { value: "Asia/Jerusalem", label: "UTC+02:00 — Jerusalem, Tel Aviv (Israel)" },
  { value: "Africa/Nairobi", label: "UTC+03:00 — Nairobi, Addis Ababa" },
  { value: "Asia/Riyadh", label: "UTC+03:00 — Riyadh, Kuwait City, Baghdad" },
  { value: "Europe/Moscow", label: "UTC+03:00 — Moscow, Saint Petersburg" },
  { value: "Asia/Tehran", label: "UTC+03:30 — Tehran (Iran)" },
  { value: "Asia/Dubai", label: "UTC+04:00 — Dubai, Abu Dhabi (UAE)" },
  { value: "Asia/Baku", label: "UTC+04:00 — Baku (Azerbaijan)" },
  { value: "Asia/Tbilisi", label: "UTC+04:00 — Tbilisi (Georgia)" },
  { value: "Asia/Kabul", label: "UTC+04:30 — Kabul (Afghanistan)" },
  { value: "Asia/Karachi", label: "UTC+05:00 — Karachi, Islamabad (Pakistan)" },
  { value: "Asia/Tashkent", label: "UTC+05:00 — Tashkent (Uzbekistan)" },
  { value: "Asia/Yekaterinburg", label: "UTC+05:00 — Yekaterinburg (Russia)" },
  { value: "Asia/Kolkata", label: "UTC+05:30 — Mumbai, Delhi, Kolkata (India)" },
  { value: "Asia/Colombo", label: "UTC+05:30 — Colombo (Sri Lanka)" },
  { value: "Asia/Kathmandu", label: "UTC+05:45 — Kathmandu (Nepal)" },
  { value: "Asia/Dhaka", label: "UTC+06:00 — Dhaka (Bangladesh)" },
  { value: "Asia/Almaty", label: "UTC+06:00 — Almaty (Kazakhstan)" },
  { value: "Asia/Yangon", label: "UTC+06:30 — Yangon (Myanmar)" },
  { value: "Asia/Bangkok", label: "UTC+07:00 — Bangkok (Thailand)" },
  { value: "Asia/Ho_Chi_Minh", label: "UTC+07:00 — Ho Chi Minh, Hanoi (Vietnam)" },
  { value: "Asia/Jakarta", label: "UTC+07:00 — Jakarta (Indonesia WIB)" },
  { value: "Asia/Novosibirsk", label: "UTC+07:00 — Novosibirsk (Russia)" },
  { value: "Asia/Shanghai", label: "UTC+08:00 — Shanghai, Beijing (China)" },
  { value: "Asia/Singapore", label: "UTC+08:00 — Singapore, Kuala Lumpur" },
  { value: "Asia/Manila", label: "UTC+08:00 — Manila (Philippines)" },
  { value: "Asia/Taipei", label: "UTC+08:00 — Taipei (Taiwan)" },
  { value: "Asia/Makassar", label: "UTC+08:00 — Makassar (Indonesia WITA)" },
  { value: "Australia/Perth", label: "UTC+08:00 — Perth (Australia)" },
  { value: "Asia/Tokyo", label: "UTC+09:00 — Tokyo, Osaka (Japan)" },
  { value: "Asia/Seoul", label: "UTC+09:00 — Seoul (South Korea)" },
  { value: "Asia/Jayapura", label: "UTC+09:00 — Jayapura (Indonesia WIT)" },
  { value: "Australia/Darwin", label: "UTC+09:30 — Darwin (Australia)" },
  { value: "Australia/Adelaide", label: "UTC+09:30 — Adelaide (Australia)" },
  { value: "Australia/Sydney", label: "UTC+10:00 — Sydney, Melbourne (Australia)" },
  { value: "Pacific/Port_Moresby", label: "UTC+10:00 — Port Moresby (Papua New Guinea)" },
  { value: "Pacific/Guadalcanal", label: "UTC+11:00 — Guadalcanal (Solomon Islands)" },
  { value: "Pacific/Auckland", label: "UTC+12:00 — Auckland, Wellington (New Zealand)" },
  { value: "Pacific/Fiji", label: "UTC+12:00 — Suva (Fiji)" },
  { value: "Pacific/Tongatapu", label: "UTC+13:00 — Nuku'alofa (Tonga)" },
  { value: "Pacific/Kiritimati", label: "UTC+14:00 — Kiritimati (Kiribati)" },
];

const API_PROVIDERS = [
  {
    group: "Core LLM", options: [
      { value: "openai", label: "OpenAI" },
      { value: "anthropic", label: "Anthropic" },
      { value: "google", label: "Google (Gemini)" },
      { value: "xai", label: "xAI (Grok)" },
      { value: "mistral", label: "Mistral" },
      { value: "deepseek", label: "DeepSeek" },
      { value: "cohere", label: "Cohere" },
      { value: "ai21", label: "AI21" },
    ]
  },
  {
    group: "China LLM API", options: [
      { value: "alibaba", label: "Alibaba (Qwen)" },
      { value: "zhipu", label: "Zhipu (GLM)" },
      { value: "moonshot", label: "Moonshot (Kimi)" },
      { value: "tencent", label: "Tencent (Hunyuan)" },
      { value: "bytedance", label: "ByteDance (Seed)" },
      { value: "minimax", label: "MiniMax" },
    ]
  },
  {
    group: "Multimodal / Video / Image", options: [
      { value: "stability", label: "Stability AI" },
      { value: "blackforest", label: "Black Forest Labs" },
      { value: "runway", label: "Runway" },
      { value: "luma", label: "Luma AI" },
      { value: "sora", label: "OpenAI Sora" },
    ]
  },
  {
    group: "AI Search API (Agents / RAG)", options: [
      { value: "brave", label: "Brave Search" },
      { value: "perplexity", label: "Perplexity" },
      { value: "youcom", label: "You.com" },
      { value: "exa", label: "Exa Search" },
      { value: "tavily", label: "Tavily" },
    ]
  },
  {
    group: "Cloud & Platforms", options: [
      { value: "azure-openai-responses", label: "Azure OpenAI Responses" },
      { value: "amazon-bedrock", label: "Amazon Bedrock" },
      { value: "google-vertex", label: "Google Vertex AI" },
      { value: "nim", label: "NVIDIA NIM" },
      { value: "github-copilot", label: "GitHub Copilot" },
    ]
  },
  {
    group: "Gateways / Routers / Inference", options: [
      { value: "openrouter", label: "OpenRouter" },
      { value: "together", label: "Together AI" },
      { value: "replicate", label: "Replicate" },
      { value: "fireworks", label: "Fireworks AI" },
      { value: "huggingface", label: "HuggingFace Inference" },
      { value: "groq", label: "Groq" },
      { value: "cerebras", label: "Cerebras" },
      { value: "deepinfra", label: "DeepInfra" },
      { value: "anyscale", label: "Anyscale" },
      { value: "baseten", label: "Baseten" },
      { value: "modal", label: "Modal" },
      { value: "runpod", label: "RunPod" },
      { value: "octoai", label: "OctoAI" },
      { value: "banana", label: "Banana.dev" },
      { value: "portkey", label: "Portkey" },
      { value: "helicone", label: "Helicone" },
      { value: "langdock", label: "Langdock" },
      { value: "edenai", label: "Eden AI" },
      { value: "aiproxy", label: "AIProxy" },
      { value: "inferencenet", label: "Inference.net" },
      { value: "jina", label: "Jina AI" },
      { value: "vercel-ai-gateway", label: "Vercel AI Gateway" },
      { value: "langfuse", label: "Langfuse" },
      { value: "humanloop", label: "Humanloop" },
      { value: "galileo", label: "Galileo AI" },
    ]
  },
  {
    group: "Universal AI API Frameworks", options: [
      { value: "litellm", label: "LiteLLM" },
      { value: "langchain", label: "LangChain" },
      { value: "llamaindex", label: "LlamaIndex" },
      { value: "vercel-sdk", label: "Vercel AI SDK" },
    ]
  },
  {
    group: "Local & Internal Providers", options: [
      { value: "ollama", label: "Ollama" },
      { value: "localai", label: "LocalAI" },
      { value: "vllm", label: "vLLM" },
      { value: "lmstudio", label: "LM Studio" },
      { value: "google-antigravity", label: "Google Antigravity" },
      { value: "google-gemini-cli", label: "Google Gemini CLI" },
      { value: "opencode", label: "OpenCode" },
      { value: "opencode-go", label: "OpenCode GO" },
      { value: "kimi-coding", label: "Kimi Coding" },
      { value: "minimax-cn", label: "MiniMax CN" },
      { value: "openai-codex", label: "OpenAI Codex" },
      { value: "zai", label: "ZAI" },
      { value: "custom", label: "Custom / Local URL" },
    ]
  }
];

const LOCAL_PROVIDER_IDS = ["ollama", "localai", "vllm", "lmstudio"] as const;
type LocalProviderId = (typeof LOCAL_PROVIDER_IDS)[number];

type LocalProviderScanResult = {
  id: LocalProviderId;
  label: string;
  baseUrl: string;
  available: boolean;
  models: Array<{ id: string; name: string }>;
  error?: string;
};

const PROVIDER_MODELS: Record<string, { value: string, label: string }[]> = {
  "openai": [
    { value: "gpt-5.4", label: "GPT-5.4" },
    { value: "gpt-5.4-pro", label: "GPT-5.4 Pro" },
    { value: "gpt-5.3", label: "GPT-5.3 (~200k)" },
    { value: "gpt-5.3-instant", label: "GPT-5.3 Instant" },
    { value: "gpt-5.3-codex", label: "GPT-5.3 Codex" },
    { value: "gpt-5.2-pro", label: "GPT-5.2 Pro (~200k)" },
    { value: "gpt-5.1", label: "GPT-5.1 (~200k)" },
    { value: "gpt-4.5-turbo", label: "GPT-4.5 Turbo" },
    { value: "gpt-4.1", label: "GPT-4.1 (~128k)" },
    { value: "gpt-4o", label: "GPT-4o (multimodal)" },
    { value: "o1", label: "o1" },
    { value: "o1-mini", label: "o1 Mini" },
    { value: "sora", label: "Sora" },
  ],
  "anthropic": [
    { value: "claude-4-6-opus", label: "Claude Opus 4.6 (~1M)" },
    { value: "claude-4-6-sonnet", label: "Claude Sonnet 4.6 (~1M)" },
    { value: "claude-4-6-haiku", label: "Claude Haiku 4.6 (~200k)" },
  ],
  "google": [
    { value: "gemini-3.1-pro", label: "Gemini 3.1 Pro (~1M)" },
    { value: "gemini-3.1-flash", label: "Gemini 3.1 Flash (~1M)" },
    { value: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite (~1M)" },
    { value: "veo-3", label: "Veo 3" },
  ],
  "xai": [
    { value: "grok-4.20", label: "Grok 4.20" },
    { value: "grok-4.1", label: "Grok 4.1 (~200k)" },
    { value: "grok-4", label: "Grok 4 (~200k)" },
    { value: "grok-imagine-1.0", label: "Grok Imagine 1.0" },
  ],
  "meta": [
    { value: "llama-4-maverick", label: "Llama 4 Maverick" },
    { value: "llama-4-scout", label: "Llama 4 Scout" },
    { value: "llama-3.3", label: "Llama 3.3" },
    { value: "llama-3.1", label: "Llama 3.1" },
  ],
  "mistral": [
    { value: "mistral-large-3", label: "Mistral Large 3" },
    { value: "mistral-large-2", label: "Mistral Large 2" },
    { value: "mistral-medium", label: "Mistral Medium" },
    { value: "ministral-3", label: "Ministral 3" },
    { value: "mixtral", label: "Mixtral" },
  ],
  "deepseek": [
    { value: "deepseek-v4", label: "DeepSeek V4" },
    { value: "deepseek-v3.2", label: "DeepSeek V3.2" },
    { value: "deepseek-v3", label: "DeepSeek V3" },
    { value: "deepseek-r1", label: "DeepSeek R1" },
  ],
  "cohere": [
    { value: "command-r-plus", label: "Command R+" },
    { value: "command-r", label: "Command R" },
    { value: "aya-expanse", label: "Aya Expanse" },
  ],
  "ai21": [
    { value: "jamba-1.5-large", label: "Jamba 1.5 Large" },
    { value: "jamba", label: "Jamba" },
    { value: "jurassic-2", label: "Jurassic-2" },
  ],
  "alibaba": [
    { value: "qwen-3.5", label: "Qwen 3.5" },
    { value: "qwen-3.5-397b", label: "Qwen 3.5 397B" },
    { value: "qwen-3", label: "Qwen 3" },
    { value: "qwen-2.5", label: "Qwen 2.5" },
  ],
  "zhipu": [
    { value: "glm-5", label: "GLM-5" },
    { value: "glm-4", label: "GLM-4" },
  ],
  "moonshot": [
    { value: "kimi-k2.5", label: "Kimi K2.5" },
    { value: "kimi-k2", label: "Kimi K2" },
  ],
  "minimax": [
    { value: "minimax-m2.5", label: "MiniMax M2.5" },
  ],
  "tencent": [
    { value: "hunyuan-turbo-s", label: "Hunyuan Turbo S" },
    { value: "hunyuan", label: "Hunyuan" },
  ],
  "bytedance": [
    { value: "seed", label: "Seed" },
    { value: "doubao-vision", label: "Doubao Vision" },
  ],
  "stability": [
    { value: "stable-diffusion-3.5", label: "Stable Diffusion 3.5" },
  ],
  "blackforest": [
    { value: "flux-1", label: "FLUX-1" },
  ],
  "runway": [
    { value: "gen-4", label: "Gen-4" },
  ],
  "luma": [
    { value: "dream-machine", label: "Dream Machine" },
  ],
  "brave": [
    { value: "brave-search", label: "Brave Search API" },
  ],
  "perplexity": [
    { value: "perplexity-api", label: "Perplexity API" },
    { value: "sonar-reasoning-pro", label: "Sonar Reasoning Pro" },
  ],
  "youcom": [
    { value: "you-api", label: "You API" },
  ],
  "exa": [
    { value: "exa-search", label: "Exa Search API" },
  ],
  "tavily": [
    { value: "tavily-api", label: "Tavily API" },
  ]
};

const GESTURE_LABELS: Record<GestureKey, string> = {
  thumbs_up: "Thumbs Up",
  fist: "Fist",
  open_hand: "Open Hand",
  peace: "Peace",
  point_up: "Point Up",
};

const STT_LANGUAGES = [
  { value: "vi-VN", label: "Vietnamese (vi-VN)" },
  { value: "en-US", label: "English US (en-US)" },
  { value: "en-GB", label: "English UK (en-GB)" },
  { value: "ja-JP", label: "Japanese (ja-JP)" },
  { value: "ko-KR", label: "Korean (ko-KR)" },
  { value: "zh-CN", label: "Chinese Simplified (zh-CN)" },
];

const IRONMAN_ACTIONS: { value: IronManAction; label: string }[] = [
  { value: "approve_hitl", label: "Open HITL" },
  { value: "stop_stream", label: "Stop Stream" },
  { value: "clear_input", label: "Clear Input" },
  { value: "new_session", label: "New Session" },
  { value: "submit_input", label: "Submit Input" },
  { value: "none", label: "None" },
];

export default function SettingsPage() {
  const { data: session, update } = useSession();
  const [activeTab, setActiveTab] = React.useState("general");
  const [apiKey, setApiKey] = React.useState(session?.apiKey ?? "");
  const [showKey, setShowKey] = React.useState(false);
  const [settings, setSettings] = React.useState<UserSettings>(defaultSettings);
  const [localProviderModels, setLocalProviderModels] = React.useState<Array<{ value: string; label: string }>>([]);
  const [detectedLocalProviders, setDetectedLocalProviders] = React.useState<LocalProviderScanResult[]>([]);
  const [scanLoading, setScanLoading] = React.useState(false);
  const [scanError, setScanError] = React.useState<string | null>(null);
  const [manualModelInput, setManualModelInput] = React.useState("");
  const [googleMapsKeyInput, setGoogleMapsKeyInput] = React.useState("");
  const [googleMapsMasked, setGoogleMapsMasked] = React.useState("");
  const [googleMapsHasKey, setGoogleMapsHasKey] = React.useState(false);
  const [googleMapsLoading, setGoogleMapsLoading] = React.useState(false);
  const [tokenProfiles, setTokenProfiles] = React.useState<TokenProfile[]>([]);
  const [tokenProfilesLoading, setTokenProfilesLoading] = React.useState(false);
  const [profileIdInput, setProfileIdInput] = React.useState("dev-cloud");
  const [profileScopesInput, setProfileScopesInput] = React.useState("chat.read,chat.write");
  const [profileExpiryDaysInput, setProfileExpiryDaysInput] = React.useState("30");
  const [profileTokenInput, setProfileTokenInput] = React.useState("");
  const [ironManSettings, setIronManSettings] = React.useState<IronManSettings>(
    defaultIronManSettings
  );

  const isLocalProviderSelected = LOCAL_PROVIDER_IDS.includes(
    settings.apiProvider as LocalProviderId
  );

  const scanLocalProviders = React.useCallback(async () => {
    setScanLoading(true);
    setScanError(null);
    try {
      const res = await fetch("/api/local-providers", { cache: "no-store" });
      const payload = (await res.json()) as { providers?: LocalProviderScanResult[] };
      setDetectedLocalProviders(payload.providers ?? []);
    } catch (error) {
      setScanError(error instanceof Error ? error.message : "Unable to scan local providers.");
      setDetectedLocalProviders([]);
    } finally {
      setScanLoading(false);
    }
  }, []);

  React.useEffect(() => {
    setApiKey(session?.apiKey ?? "");
  }, [session?.apiKey]);

  React.useEffect(() => {
    setSettings({ ...readUserSettings(), language: "en" });
  }, []);

  React.useEffect(() => {
    setIronManSettings(getIronManSettings());
  }, []);

  React.useEffect(() => {
    if (!isLocalProviderSelected) return;

    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`/api/models?provider=${encodeURIComponent(settings.apiProvider)}`, { cache: "no-store" });
        const payload = (await res.json()) as {
          models?: Array<{ model_id?: string; model_name?: string }>;
        };
        if (cancelled) return;
        const models = (payload.models ?? [])
          .map((model) => ({
            value: String(model.model_id ?? "").trim(),
            label: String(model.model_name ?? model.model_id ?? "").trim(),
          }))
          .filter((model) => model.value);
        setLocalProviderModels(models);
        if (models.length && !models.some((model) => model.value === settings.defaultModel)) {
          setSettings((prev) => ({ ...prev, defaultModel: models[0].value }));
        }
      } catch {
        if (!cancelled) setLocalProviderModels([]);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [settings.apiProvider, settings.defaultModel, isLocalProviderSelected]);

  React.useEffect(() => {
    void scanLocalProviders();
  }, [scanLocalProviders]);

  const loadGoogleMapsStatus = React.useCallback(async () => {
    setGoogleMapsLoading(true);
    try {
      const res = await fetch("/api/google-maps-key", { cache: "no-store" });
      if (!res.ok) {
        setGoogleMapsHasKey(false);
        setGoogleMapsMasked("");
        return;
      }
      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        return;
      }
      const payload = (await res.json()) as { has_key?: boolean; masked_key?: string; detail?: string };
      setGoogleMapsHasKey(Boolean(payload.has_key));
      setGoogleMapsMasked(String(payload.masked_key || ""));
    } catch {
      setGoogleMapsHasKey(false);
      setGoogleMapsMasked("");
    } finally {
      setGoogleMapsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadGoogleMapsStatus();
  }, [loadGoogleMapsStatus]);

  const loadTokenProfiles = React.useCallback(async () => {
    setTokenProfilesLoading(true);
    try {
      const res = await fetch("/api/token-profiles", { cache: "no-store" });
      if (!res.ok) {
        setTokenProfiles([]);
        return;
      }
      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        return;
      }
      const payload = (await res.json()) as { profiles?: TokenProfile[]; detail?: string };
      setTokenProfiles(payload.profiles ?? []);
    } catch {
      setTokenProfiles([]);
    } finally {
      setTokenProfilesLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadTokenProfiles();
  }, [loadTokenProfiles]);

  const activeModelOptions =
    isLocalProviderSelected
      ? localProviderModels
      : PROVIDER_MODELS[settings.apiProvider];

  const saveSettings = async () => {
    if (isLocalProviderSelected) {
      try {
        const res = await fetch(`/api/models?provider=${encodeURIComponent(settings.apiProvider)}`, {
          cache: "no-store",
        });
        const payload = (await res.json()) as { models?: Array<{ model_id?: string }> };
        const installedModels = (payload.models ?? [])
          .map((item) => String(item.model_id ?? "").trim())
          .filter(Boolean);

        if (installedModels.length && !installedModels.includes(settings.defaultModel)) {
          toast.error(`Model '${settings.defaultModel}' is not installed on your local ${settings.apiProvider} provider.`);
          return;
        }
      } catch {
        toast.error("Unable to validate local model. Run scan and try again.");
        return;
      }
    }

    writeUserSettings({ ...settings, language: "en" });
    setSettings((prev) => ({ ...prev, language: "en" }));
    toast.success("Settings saved");
  };

  const saveIronMan = () => {
    saveIronManSettings(ironManSettings);
    toast.success("Iron Man settings saved");
  };

  const handleSaveApiKey = async () => {
    await update({ apiKey });
    toast.success("API key saved");
  };

  const handleCopyApiKey = async () => {
    if (!apiKey) return;
    await navigator.clipboard.writeText(apiKey);
    toast.success("API key copied");
  };

  const handleRevoke = async () => {
    setApiKey("");
    await update({ apiKey: "" });
    toast.success("API key revoked");
  };

  const handleSaveGoogleMapsKey = async () => {
    const candidate = googleMapsKeyInput.trim();
    if (!candidate) {
      toast.error("Google Maps API key cannot be empty.");
      return;
    }
    if (!GOOGLE_MAPS_KEY_RE.test(candidate)) {
      toast.error("Invalid Google Maps API key format.");
      return;
    }

    setGoogleMapsLoading(true);
    try {
      const res = await fetch("/api/google-maps-key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: candidate }),
      });
      const payload = (await res.json()) as { has_key?: boolean; masked_key?: string; detail?: string };
      if (!res.ok) {
        throw new Error(payload.detail || "Unable to save Google Maps API key.");
      }
      setGoogleMapsHasKey(Boolean(payload.has_key));
      setGoogleMapsMasked(String(payload.masked_key || ""));
      setGoogleMapsKeyInput("");
      toast.success("Google Maps API key saved");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to save Google Maps API key.");
    } finally {
      setGoogleMapsLoading(false);
    }
  };

  const handleDeleteGoogleMapsKey = async () => {
    setGoogleMapsLoading(true);
    try {
      const res = await fetch("/api/google-maps-key", { method: "DELETE" });
      const payload = (await res.json()) as { detail?: string };
      if (!res.ok) {
        throw new Error(payload.detail || "Unable to delete Google Maps API key.");
      }
      setGoogleMapsHasKey(false);
      setGoogleMapsMasked("");
      setGoogleMapsKeyInput("");
      toast.success("Google Maps API key removed");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to delete Google Maps API key.");
    } finally {
      setGoogleMapsLoading(false);
    }
  };

  const handleSaveTokenProfile = async () => {
    const profile_id = profileIdInput.trim();
    const token = profileTokenInput.trim();
    const scopes = profileScopesInput
      .split(",")
      .map((scope) => scope.trim())
      .filter(Boolean);
    const expires_in_days = Number(profileExpiryDaysInput || "0");

    if (!profile_id) {
      toast.error("Token profile id is required.");
      return;
    }
    if (!token) {
      toast.error("Token value is required.");
      return;
    }

    setTokenProfilesLoading(true);
    try {
      const res = await fetch("/api/token-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_id,
          token,
          environment: "cloud",
          scopes,
          expires_in_days: Number.isFinite(expires_in_days) && expires_in_days > 0 ? expires_in_days : undefined,
        }),
      });
      const payload = (await res.json()) as { detail?: string };
      if (!res.ok) {
        throw new Error(payload.detail || "Unable to save token profile.");
      }
      setProfileTokenInput("");
      toast.success("Token profile saved");
      await loadTokenProfiles();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to save token profile.");
    } finally {
      setTokenProfilesLoading(false);
    }
  };

  const handleUseTokenProfile = async (profileId: string) => {
    setTokenProfilesLoading(true);
    try {
      const res = await fetch(`/api/token-profiles/${encodeURIComponent(profileId)}/use`, {
        method: "POST",
      });
      const payload = (await res.json()) as { token?: string; detail?: string };
      if (!res.ok || !payload.token) {
        throw new Error(payload.detail || "Unable to activate token profile.");
      }
      await update({ apiKey: payload.token });
      setApiKey(payload.token);
      toast.success(`Token profile '${profileId}' activated`);
      await loadTokenProfiles();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to activate token profile.");
    } finally {
      setTokenProfilesLoading(false);
    }
  };

  const handleRevokeTokenProfile = async (profileId: string) => {
    setTokenProfilesLoading(true);
    try {
      const res = await fetch(`/api/token-profiles/${encodeURIComponent(profileId)}`, {
        method: "DELETE",
      });
      const payload = (await res.json()) as { detail?: string };
      if (!res.ok) {
        throw new Error(payload.detail || "Unable to revoke token profile.");
      }
      toast.success(`Token profile '${profileId}' revoked`);
      await loadTokenProfiles();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to revoke token profile.");
    } finally {
      setTokenProfilesLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Preferences
        </p>
        <h1 className="mt-2 text-3xl font-semibold">Settings</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Manage your preferences and API keys.
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="models">Models</TabsTrigger>
          <TabsTrigger value="keys">API Keys</TabsTrigger>
          <TabsTrigger value="appearance">Appearance</TabsTrigger>
          <TabsTrigger value="advanced">Advanced</TabsTrigger>
          <TabsTrigger value="gateways">Gateways</TabsTrigger>
          <TabsTrigger value="ironman">Iron Man</TabsTrigger>
        </TabsList>

        <TabsContent value="general" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Display name
                </label>
                <Input
                  value={settings.displayName}
                  onChange={(event) =>
                    setSettings((prev) => ({
                      ...prev,
                      displayName: event.target.value,
                    }))
                  }
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Language
                </label>
                <Input value="English (en)" disabled readOnly />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Timezone
                </label>
                <select
                  value={settings.timezone}
                  onChange={(e) =>
                    setSettings((prev) => ({ ...prev, timezone: e.target.value }))
                  }
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {TIMEZONES.map((tz) => (
                    <option key={tz.value} value={tz.value}>
                      {tz.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-4">
              <Button onClick={saveSettings}>Save changes</Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="models" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            {isLocalProviderSelected ? (
              <div className="mb-4 rounded-lg border border-border bg-muted/20 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">Local AI scan</p>
                    <p className="text-xs text-muted-foreground">
                      Scan providers on your machine and auto-load available models.
                    </p>
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={() => void scanLocalProviders()}>
                    {scanLoading ? "Scanning..." : "Scan local providers"}
                  </Button>
                </div>
                {scanError ? (
                  <p className="mt-2 text-xs text-destructive">{scanError}</p>
                ) : null}
                <div className="mt-3 space-y-2">
                  {detectedLocalProviders.map((provider) => (
                    <div key={provider.id} className="rounded-md border border-border/70 bg-background px-3 py-2">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="font-medium">{provider.label}</span>
                        <span className={provider.available ? "text-emerald-600" : "text-muted-foreground"}>
                          {provider.available ? `Online · ${provider.models.length} model(s)` : "Offline"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{provider.baseUrl}</p>
                      {provider.available && provider.models.length ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="mt-2 h-7 px-2 text-xs"
                          onClick={() =>
                            setSettings((prev) => ({
                              ...prev,
                              apiProvider: provider.id,
                              defaultModel: provider.models[0].id,
                            }))
                          }
                        >
                          Use {provider.label}
                        </Button>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Default model
                </label>
                {activeModelOptions?.length ? (
                  <select
                    value={settings.defaultModel}
                    onChange={(e) =>
                      setSettings((prev) => ({ ...prev, defaultModel: e.target.value }))
                    }
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    {activeModelOptions.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    value={settings.defaultModel}
                    onChange={(event) =>
                      setSettings((prev) => ({
                        ...prev,
                        defaultModel: event.target.value,
                      }))
                    }
                    placeholder="Type model name for this gateway..."
                  />
                )}
                <div className="mt-2 space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    Or enter model manually
                  </label>
                  <div className="flex gap-2">
                    <Input
                      value={manualModelInput}
                      onChange={(event) => setManualModelInput(event.target.value)}
                      placeholder="e.g. qwen2.5:7b"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        const candidate = manualModelInput.trim();
                        if (!candidate) return;
                        setSettings((prev) => ({ ...prev, defaultModel: candidate }));
                        setManualModelInput("");
                      }}
                    >
                      Use
                    </Button>
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Temperature
                </label>
                <Input
                  type="number"
                  step="0.1"
                  value={settings.temperature}
                  onChange={(event) =>
                    setSettings((prev) => ({
                      ...prev,
                      temperature: Number(event.target.value),
                    }))
                  }
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Max tokens
                </label>
                <Input
                  type="number"
                  value={settings.maxTokens}
                  onChange={(event) =>
                    setSettings((prev) => ({
                      ...prev,
                      maxTokens: Number(event.target.value),
                    }))
                  }
                />
              </div>
            </div>
            <div className="mt-4">
              <Button onClick={saveSettings}>Save model settings</Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="keys" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            <div className="text-sm font-semibold">API Key & Provider</div>
            <p className="mt-1 text-xs text-muted-foreground">
              Set the AI provider and API key used for generation.
            </p>

            <div className="mt-4 space-y-4">
              <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-4">
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    1. Select AI Provider or Gateway
                  </label>
                  <select
                    value={settings.apiProvider}
                    onChange={(e) =>
                      setSettings((prev) => {
                        const nextProvider = e.target.value;
                        const nextModel = LOCAL_PROVIDER_IDS.includes(nextProvider as LocalProviderId)
                          ? localProviderModels[0]?.value || prev.defaultModel
                          : PROVIDER_MODELS[nextProvider]?.[0]?.value || prev.defaultModel;
                        return {
                          ...prev,
                          apiProvider: nextProvider,
                          defaultModel: nextModel,
                        };
                      })
                    }
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    {API_PROVIDERS.map((group, i) => (
                      <optgroup key={i} label={group.group}>
                        {group.options.map((provider) => (
                          <option key={provider.value} value={provider.value}>
                            {provider.label}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    2. Choose Model (Updates based on Provider)
                  </label>
                  {activeModelOptions?.length ? (
                    <select
                      value={settings.defaultModel}
                      onChange={(e) =>
                        setSettings((prev) => ({ ...prev, defaultModel: e.target.value }))
                      }
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    >
                      {activeModelOptions.map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      value={settings.defaultModel}
                      onChange={(event) =>
                        setSettings((prev) => ({
                          ...prev,
                          defaultModel: event.target.value,
                        }))
                      }
                      placeholder="Type model name for this gateway/provider..."
                    />
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  API Key
                </label>
                <Input
                  type={showKey ? "text" : "password"}
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder="Enter your API key (e.g., sk-...)"
                />
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Current:</span>
                <span className="font-mono">{apiKey ? maskKey(apiKey) : "—"}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowKey((value) => !value)}
                >
                  {showKey ? "Hide" : "Show"}
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={handleCopyApiKey}>
                  Copy
                </Button>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={handleSaveApiKey}>
                  Save API Key
                </Button>
                <Button type="button" variant="outline" onClick={handleRevoke}>
                  Revoke
                </Button>
              </div>

              <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
                <div>
                  <div className="text-sm font-semibold">Google Maps API Key</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Stored via backend config API and shared with TUI.
                  </p>
                </div>
                <Input
                  type="password"
                  value={googleMapsKeyInput}
                  onChange={(event) => setGoogleMapsKeyInput(event.target.value)}
                  placeholder="Enter Google Maps API key (AIza...)"
                />
                <div className="text-xs text-muted-foreground">
                  Status: {googleMapsHasKey ? "Saved" : "Not saved"}
                  {googleMapsMasked ? ` · ${googleMapsMasked}` : ""}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" onClick={handleSaveGoogleMapsKey} disabled={googleMapsLoading}>
                    Save Maps Key
                  </Button>
                  <Button type="button" variant="outline" onClick={handleDeleteGoogleMapsKey} disabled={googleMapsLoading}>
                    Delete Maps Key
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => void loadGoogleMapsStatus()} disabled={googleMapsLoading}>
                    Refresh Status
                  </Button>
                </div>
              </div>

              <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
                <div>
                  <div className="text-sm font-semibold">Saved Token Profiles</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Create reusable token profiles with expiry/scopes and quick activate/revoke actions.
                  </p>
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  <Input
                    value={profileIdInput}
                    onChange={(event) => setProfileIdInput(event.target.value)}
                    placeholder="Profile id (e.g. dev-cloud)"
                  />
                  <Input
                    type="password"
                    value={profileTokenInput}
                    onChange={(event) => setProfileTokenInput(event.target.value)}
                    placeholder="Token value"
                  />
                  <Input
                    value={profileScopesInput}
                    onChange={(event) => setProfileScopesInput(event.target.value)}
                    placeholder="Scopes (comma-separated)"
                  />
                  <Input
                    value={profileExpiryDaysInput}
                    onChange={(event) => setProfileExpiryDaysInput(event.target.value)}
                    placeholder="Expiry days (optional)"
                  />
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button type="button" onClick={handleSaveTokenProfile} disabled={tokenProfilesLoading}>
                    Save Profile
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => void loadTokenProfiles()} disabled={tokenProfilesLoading}>
                    Refresh Profiles
                  </Button>
                </div>

                <div className="space-y-2">
                  {tokenProfiles.length === 0 ? (
                    <div className="text-xs text-muted-foreground">No token profiles saved.</div>
                  ) : (
                    tokenProfiles.map((profile) => (
                      <div key={profile.profile_id} className="rounded-md border border-border/70 bg-background px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                          <span className="font-medium">{profile.profile_id}</span>
                          <span>
                            {profile.revoked ? "revoked" : profile.expired ? "expired" : profile.expiring_soon ? "expiring soon" : "active"}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          env={profile.environment} · scopes={profile.scopes.join(",") || "-"} · last_used={formatUtcDateTime(profile.last_used_at)}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={tokenProfilesLoading || profile.revoked || profile.expired || !profile.has_token}
                            onClick={() => void handleUseTokenProfile(profile.profile_id)}
                          >
                            Use
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={tokenProfilesLoading || profile.revoked}
                            onClick={() => void handleRevokeTokenProfile(profile.profile_id)}
                          >
                            Revoke
                          </Button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="appearance" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Theme
                </label>
                <Input
                  value={settings.theme}
                  onChange={(event) =>
                    setSettings((prev) => ({
                      ...prev,
                      theme: event.target.value as UserSettings["theme"],
                    }))
                  }
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Font size
                </label>
                <Input
                  value={settings.fontSize}
                  onChange={(event) =>
                    setSettings((prev) => ({
                      ...prev,
                      fontSize: event.target.value as UserSettings["fontSize"],
                    }))
                  }
                />
              </div>
            </div>
            <div className="mt-4">
              <Button onClick={saveSettings}>Save appearance</Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="advanced" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold">Enable cache</div>
                <div className="text-xs text-muted-foreground">
                  Semantic cache for repeated requests.
                </div>
              </div>
              <Switch
                checked={settings.cacheEnabled}
                onCheckedChange={(value) =>
                  setSettings((prev) => ({ ...prev, cacheEnabled: value }))
                }
              />
            </div>
            <div className="mt-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold">Enable compression</div>
                <div className="text-xs text-muted-foreground">
                  Token compression layer.
                </div>
              </div>
              <Switch
                checked={settings.compressionEnabled}
                onCheckedChange={(value) =>
                  setSettings((prev) => ({ ...prev, compressionEnabled: value }))
                }
              />
            </div>
            <div className="mt-4">
              <label className="text-xs font-medium text-muted-foreground">
                Log level
              </label>
              <Input
                className="mt-2"
                value={settings.logLevel}
                onChange={(event) =>
                  setSettings((prev) => ({
                    ...prev,
                    logLevel: event.target.value as UserSettings["logLevel"],
                  }))
                }
              />
            </div>
            <div className="mt-4">
              <Button onClick={saveSettings}>Save advanced</Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="gateways" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            <div className="flex flex-col gap-2 mb-6">
              <h2 className="text-xl font-semibold">Remote Gateway Connections</h2>
              <p className="text-sm text-muted-foreground">
                Attach external IronCore worker nodes or remote proxy endpoints to scale your autonomous fleet globally.
              </p>
            </div>

            <div className="space-y-4 border rounded-md p-4 bg-card/50">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="font-semibold text-sm">EU-West Compute Pool</span>
                </div>
                <span className="text-xs bg-muted px-2 py-1 rounded">ironcore-pool-01</span>
              </div>
              <div className="text-xs text-muted-foreground font-mono">wss://eu-west.gateway.ironcore.dev/v2/stream</div>
              <div className="flex justify-end gap-2 mt-2">
                <Button variant="outline" size="sm">Rotate Token</Button>
                <Button variant="destructive" size="sm">Disconnect Node</Button>
              </div>
            </div>

            <div className="mt-8 pt-6 border-t border-border">
              <h3 className="font-medium text-sm mb-4">Register New Gateway</h3>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Gateway URL (WSS or HTTPS)</label>
                  <Input placeholder="wss://node.example.com/stream" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Authentication Token</label>
                  <Input type="password" placeholder="ic_gateway_..." />
                </div>
              </div>
              <div className="mt-4 flex justify-end">
                <Button className="bg-primary text-primary-foreground hover:bg-primary/90">
                  Verify & Connect Operator
                </Button>
              </div>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="ironman" className="space-y-4">
          <Card className="border border-border/60 bg-background/80 p-6">
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    Speech language
                  </label>
                  <select
                    value={ironManSettings.sttLanguage}
                    onChange={(event) =>
                      setIronManSettings((prev) => ({
                        ...prev,
                        sttLanguage: event.target.value,
                      }))
                    }
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    {STT_LANGUAGES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    Gesture sensitivity: {ironManSettings.gestureSensitivity.toFixed(2)}
                  </label>
                  <input
                    type="range"
                    min={0.1}
                    max={1}
                    step={0.05}
                    value={ironManSettings.gestureSensitivity}
                    onChange={(event) =>
                      setIronManSettings((prev) => ({
                        ...prev,
                        gestureSensitivity: Number(event.target.value),
                      }))
                    }
                    className="w-full"
                  />
                </div>
              </div>

              <div className="rounded-md border border-border/60 p-4">
                <div className="mb-3 text-sm font-semibold">Gesture mapping</div>
                <div className="space-y-3">
                  {(Object.keys(GESTURE_LABELS) as GestureKey[]).map((gesture) => (
                    <div key={gesture} className="grid items-center gap-3 md:grid-cols-[1fr_auto_220px]">
                      <div className="text-sm">{GESTURE_LABELS[gesture]}</div>
                      <div className="flex items-center gap-2">
                        <Switch
                          checked={ironManSettings.enabledGestures[gesture]}
                          onCheckedChange={(value) =>
                            setIronManSettings((prev) => ({
                              ...prev,
                              enabledGestures: {
                                ...prev.enabledGestures,
                                [gesture]: value,
                              },
                            }))
                          }
                        />
                        <span className="text-xs text-muted-foreground">Enabled</span>
                      </div>
                      <select
                        value={ironManSettings.gestureMap[gesture]}
                        onChange={(event) =>
                          setIronManSettings((prev) => ({
                            ...prev,
                            gestureMap: {
                              ...prev.gestureMap,
                              [gesture]: event.target.value as IronManAction,
                            },
                          }))
                        }
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                      >
                        {IRONMAN_ACTIONS.map((item) => (
                          <option key={item.value} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between rounded-md border border-border/60 p-4">
                <div>
                  <div className="text-sm font-semibold">Test mode</div>
                  <div className="text-xs text-muted-foreground">
                    Keep manual testing enabled and show on-screen status.
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Switch
                    checked={ironManSettings.testMode}
                    onCheckedChange={(value) =>
                      setIronManSettings((prev) => ({
                        ...prev,
                        testMode: value,
                      }))
                    }
                  />
                  <span className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
                    {ironManSettings.testMode ? "TEST MODE ON" : "TEST MODE OFF"}
                  </span>
                </div>
              </div>

              <div className="flex justify-end">
                <Button onClick={saveIronMan}>Save Iron Man settings</Button>
              </div>
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
