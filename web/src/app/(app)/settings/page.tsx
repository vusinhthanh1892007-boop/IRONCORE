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
import { useI18n } from "@/components/providers/I18nProvider";

const maskKey = (key: string) => {
  if (key.length <= 6) return key;
  return `${key.slice(0, 2)}-****-****-${key.slice(-4)}`;
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
  { value: "Asia/Ho_Chi_Minh", label: "UTC+07:00 — Hồ Chí Minh, Hà Nội (Việt Nam)" },
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
  const { language, setLanguage, options } = useI18n();
  const [activeTab, setActiveTab] = React.useState("general");
  const [apiKey, setApiKey] = React.useState(session?.apiKey ?? "");
  const [showKey, setShowKey] = React.useState(false);
  const [settings, setSettings] = React.useState<UserSettings>(defaultSettings);
  const [ollamaModels, setOllamaModels] = React.useState<Array<{ value: string; label: string }>>([]);
  const [ironManSettings, setIronManSettings] = React.useState<IronManSettings>(
    defaultIronManSettings
  );

  React.useEffect(() => {
    setApiKey(session?.apiKey ?? "");
  }, [session?.apiKey]);

  React.useEffect(() => {
    setSettings({ ...readUserSettings(), language });
  }, [language]);

  React.useEffect(() => {
    setIronManSettings(getIronManSettings());
  }, []);

  React.useEffect(() => {
    if (settings.apiProvider !== "ollama") return;

    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/models?provider=ollama", { cache: "no-store" });
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
        setOllamaModels(models);
        if (models.length && !models.some((model) => model.value === settings.defaultModel)) {
          setSettings((prev) => ({ ...prev, defaultModel: models[0].value }));
        }
      } catch {
        if (!cancelled) setOllamaModels([]);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [settings.apiProvider, settings.defaultModel]);

  const activeModelOptions =
    settings.apiProvider === "ollama"
      ? ollamaModels
      : PROVIDER_MODELS[settings.apiProvider];

  const saveSettings = () => {
    writeUserSettings(settings);
    setLanguage(settings.language);
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
                <select
                  value={settings.language}
                  onChange={(event) =>
                    setSettings((prev) => ({
                      ...prev,
                      language: event.target.value,
                    }))
                  }
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {options.map((option) => (
                    <option key={option.code} value={option.code}>
                      {option.label}
                    </option>
                  ))}
                </select>
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
                      setSettings((prev) => ({
                        ...prev,
                        apiProvider: e.target.value,
                        defaultModel: PROVIDER_MODELS[e.target.value]?.[0]?.value || prev.defaultModel
                      }))
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
