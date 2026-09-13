export const AI_CATALOG_LAST_UPDATED = "2026-03-12";
export const AI_CATALOG_PAGE_SIZE = 20;

export interface CatalogModel {
  model_id: string;
  model_name: string;
  short_description: string;
  context_window?: number;
  tags: string[];
  example_endpoint_if_known?: string;
}

export interface CatalogProvider {
  id: string;
  name: string;
  section_id: string;
  short_description: string;
  preview: string;
  models: CatalogModel[];
}

export interface CatalogSection {
  id: string;
  title: string;
  description: string;
}

export const CATALOG_SECTIONS: CatalogSection[] = [
  {
    id: "open-source-llm-api",
    title: "2️⃣ Open-source LLMs with API",
    description: "Provider → Model matrix for popular open-weight LLMs and ecosystems.",
  },
  {
    id: "chinese-llm-api",
    title: "3️⃣ Chinese LLM APIs",
    description: "Provider → Model matrix for Chinese AI providers.",
  },
  {
    id: "multimodal-video-image-api",
    title: "4️⃣ Multimodal / Video / Image APIs",
    description: "Provider → Model matrix for image, video, and multimodal APIs.",
  },
  {
    id: "ai-search-api",
    title: "5️⃣ AI Search & Retrieval APIs",
    description: "Platform → API matrix for neural search and RAG retrieval.",
  },
  {
    id: "gateway-inference-platform",
    title: "6️⃣ AI Gateways & Inference Platforms",
    description: "Popular AI gateway, router, and managed inference platforms.",
  },
  {
    id: "universal-ai-api",
    title: "7️⃣ Open-Source Universal AI APIs & Frameworks",
    description: "Projects classified by SDK, agent framework, inference engine, and orchestration.",
  },
];

const baseProviders: CatalogProvider[] = [
  {
    id: "meta",
    name: "Meta",
    section_id: "open-source-llm-api",
    short_description: "Open-weight Llama ecosystem with broad inference support.",
    preview: "Llama family",
    models: [
      {
        model_id: "meta/llama4-maverick",
        model_name: "Llama 4 Maverick",
        short_description: "Large open-weight model optimized for reasoning workloads.",
        context_window: 128000,
        tags: ["open-weight", "inference", "reasoning"],
        example_endpoint_if_known: "/v1/chat/completions",
      },
      {
        model_id: "meta/llama4-scout",
        model_name: "Llama 4 Scout",
        short_description: "Smaller footprint variant for lower-latency deployments.",
        context_window: 32768,
        tags: ["efficient", "open-weight"],
      },
    ],
  },
  {
    id: "mistral",
    name: "Mistral",
    section_id: "open-source-llm-api",
    short_description: "Mistral API and open-weight model family.",
    preview: "Mistral Large / Medium",
    models: [
      {
        model_id: "mistral/mistral-large-3",
        model_name: "Mistral Large 3",
        short_description: "Top-tier Mistral reasoning and coding model.",
        context_window: 128000,
        tags: ["reasoning", "coding"],
      },
    ],
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    section_id: "open-source-llm-api",
    short_description: "DeepSeek model line for coding and long-context reasoning.",
    preview: "DeepSeek V3 / R1",
    models: [
      {
        model_id: "deepseek/deepseek-v3",
        model_name: "DeepSeek V3",
        short_description: "General-purpose high-capability model.",
        context_window: 128000,
        tags: ["reasoning", "general"],
      },
      {
        model_id: "deepseek/deepseek-r1",
        model_name: "DeepSeek R1",
        short_description: "Reasoning-focused model with strong chain-of-thought style outputs.",
        context_window: 128000,
        tags: ["reasoning", "advanced"],
      },
    ],
  },
  {
    id: "cohere",
    name: "Cohere",
    section_id: "open-source-llm-api",
    short_description: "Enterprise-friendly language models and retrieval tooling.",
    preview: "Command R family",
    models: [
      {
        model_id: "cohere/command-r-plus",
        model_name: "Command R+",
        short_description: "Cohere flagship for enterprise retrieval-augmented tasks.",
        context_window: 128000,
        tags: ["enterprise", "rag"],
      },
    ],
  },
  {
    id: "ai21",
    name: "AI21",
    section_id: "open-source-llm-api",
    short_description: "AI21 language models and orchestration APIs.",
    preview: "Jamba line",
    models: [
      {
        model_id: "ai21/jamba-1.5-large",
        model_name: "Jamba 1.5 Large",
        short_description: "Hybrid architecture model with long-context support.",
        context_window: 256000,
        tags: ["hybrid", "long-context"],
      },
    ],
  },
  {
    id: "openai",
    name: "OpenAI",
    section_id: "open-source-llm-api",
    short_description: "General and multimodal foundation models.",
    preview: "GPT / o-series",
    models: [
      {
        model_id: "openai/gpt-5.3-codex",
        model_name: "GPT-5.3 Codex",
        short_description: "Code-specialized model for engineering workflows.",
        context_window: 200000,
        tags: ["coding", "tool-use"],
      },
      {
        model_id: "openai/gpt-4o",
        model_name: "GPT-4o",
        short_description: "Multimodal low-latency flagship model.",
        context_window: 128000,
        tags: ["multimodal", "general"],
      },
    ],
  },
  {
    id: "google",
    name: "Google",
    section_id: "open-source-llm-api",
    short_description: "Gemini model family and generative APIs.",
    preview: "Gemini 3.1 line",
    models: [
      {
        model_id: "google/gemini-3.1-pro",
        model_name: "Gemini 3.1 Pro",
        short_description: "High-end Gemini model for deep reasoning.",
        context_window: 1000000,
        tags: ["reasoning", "long-context"],
      },
    ],
  },

  {
    id: "alibaba",
    name: "Alibaba",
    section_id: "chinese-llm-api",
    short_description: "Qwen ecosystem via Alibaba cloud APIs.",
    preview: "Qwen family",
    models: [
      {
        model_id: "alibaba/qwen-3.5",
        model_name: "Qwen 3.5",
        short_description: "Large Chinese/English capable model.",
        context_window: 128000,
        tags: ["bilingual", "general"],
      },
    ],
  },
  {
    id: "zhipu",
    name: "Zhipu",
    section_id: "chinese-llm-api",
    short_description: "GLM model APIs by Zhipu AI.",
    preview: "GLM 4/5",
    models: [
      {
        model_id: "zhipu/glm-5",
        model_name: "GLM-5",
        short_description: "General-purpose GLM generation model.",
        context_window: 128000,
        tags: ["general", "chinese"],
      },
    ],
  },
  {
    id: "moonshot",
    name: "Moonshot",
    section_id: "chinese-llm-api",
    short_description: "Kimi models for long context workloads.",
    preview: "Kimi K2 line",
    models: [
      {
        model_id: "moonshot/kimi-k2.5",
        model_name: "Kimi K2.5",
        short_description: "Long-context model tuned for productivity use cases.",
        context_window: 200000,
        tags: ["long-context", "assistant"],
      },
    ],
  },
  {
    id: "minimax",
    name: "MiniMax",
    section_id: "chinese-llm-api",
    short_description: "MiniMax model APIs.",
    preview: "M2.5",
    models: [
      {
        model_id: "minimax/minimax-m2.5",
        model_name: "MiniMax M2.5",
        short_description: "General-purpose model optimized for efficiency.",
        context_window: 128000,
        tags: ["efficient", "general"],
      },
    ],
  },
  {
    id: "tencent",
    name: "Tencent",
    section_id: "chinese-llm-api",
    short_description: "Hunyuan family via Tencent cloud APIs.",
    preview: "Hunyuan",
    models: [
      {
        model_id: "tencent/hunyuan-turbo-s",
        model_name: "Hunyuan Turbo S",
        short_description: "Fast model for interactive workloads.",
        context_window: 64000,
        tags: ["fast", "chat"],
      },
    ],
  },
  {
    id: "bytedance",
    name: "ByteDance",
    section_id: "chinese-llm-api",
    short_description: "Seed/Doubao model APIs.",
    preview: "Seed",
    models: [
      {
        model_id: "bytedance/seed",
        model_name: "Seed",
        short_description: "General model from ByteDance ecosystem.",
        context_window: 128000,
        tags: ["general", "chinese"],
      },
    ],
  },

  {
    id: "stability-ai",
    name: "Stability AI",
    section_id: "multimodal-video-image-api",
    short_description: "Image generation APIs for SD model line.",
    preview: "Stable Diffusion",
    models: [
      {
        model_id: "stability-ai/stable-diffusion-3.5",
        model_name: "Stable Diffusion 3.5",
        short_description: "Image generation model for creative pipelines.",
        tags: ["image", "generation"],
        example_endpoint_if_known: "/v1/images/generations",
      },
    ],
  },
  {
    id: "black-forest-labs",
    name: "Black Forest Labs",
    section_id: "multimodal-video-image-api",
    short_description: "FLUX model family for image synthesis.",
    preview: "FLUX",
    models: [
      {
        model_id: "black-forest-labs/flux-1",
        model_name: "FLUX.1",
        short_description: "High-fidelity image generation model.",
        tags: ["image", "flux"],
      },
    ],
  },
  {
    id: "runway",
    name: "Runway",
    section_id: "multimodal-video-image-api",
    short_description: "Video generation and editing APIs.",
    preview: "Gen-4",
    models: [
      {
        model_id: "runway/gen-4",
        model_name: "Runway Gen-4",
        short_description: "Video generation model for cinematic outputs.",
        tags: ["video", "generation"],
      },
    ],
  },
  {
    id: "luma-ai",
    name: "Luma AI",
    section_id: "multimodal-video-image-api",
    short_description: "Video generation and 3D capture APIs.",
    preview: "Dream Machine",
    models: [
      {
        model_id: "luma-ai/dream-machine",
        model_name: "Dream Machine",
        short_description: "Video generation model optimized for storytelling clips.",
        tags: ["video", "creative"],
      },
    ],
  },

  {
    id: "brave",
    name: "Brave",
    section_id: "ai-search-api",
    short_description: "Search API suitable for agents and RAG.",
    preview: "Brave Search API",
    models: [
      {
        model_id: "brave/brave-search-api",
        model_name: "Brave Search API",
        short_description: "Web search endpoint for retrieval pipelines.",
        tags: ["search", "rag"],
        example_endpoint_if_known: "/res/v1/web/search",
      },
    ],
  },
  {
    id: "perplexity",
    name: "Perplexity",
    section_id: "ai-search-api",
    short_description: "Search-grounded LLM APIs.",
    preview: "Sonar line",
    models: [
      {
        model_id: "perplexity/sonar-reasoning-pro",
        model_name: "Sonar Reasoning Pro",
        short_description: "Search-augmented reasoning model.",
        context_window: 128000,
        tags: ["search", "reasoning"],
      },
    ],
  },
  {
    id: "you-com",
    name: "You.com",
    section_id: "ai-search-api",
    short_description: "Search and AI answer APIs.",
    preview: "You API",
    models: [
      {
        model_id: "you-com/you-api",
        model_name: "You API",
        short_description: "Query and answer API for search-grounded apps.",
        tags: ["search", "api"],
      },
    ],
  },
  {
    id: "exa",
    name: "Exa",
    section_id: "ai-search-api",
    short_description: "Semantic web search API.",
    preview: "Exa Search",
    models: [
      {
        model_id: "exa/exa-search",
        model_name: "Exa Search",
        short_description: "Semantic retrieval API for agents.",
        tags: ["semantic-search", "rag"],
      },
    ],
  },
  {
    id: "tavily",
    name: "Tavily",
    section_id: "ai-search-api",
    short_description: "Agent-first search API.",
    preview: "Tavily API",
    models: [
      {
        model_id: "tavily/tavily-api",
        model_name: "Tavily API",
        short_description: "Web search endpoint designed for LLM agents.",
        tags: ["agent", "search"],
      },
    ],
  },

  {
    id: "openrouter",
    name: "OpenRouter",
    section_id: "gateway-inference-platform",
    short_description: "Unified router to many model providers.",
    preview: "Multi-provider router",
    models: [{ model_id: "openrouter/router", model_name: "OpenRouter Route", short_description: "Route across many hosted models.", tags: ["gateway", "routing"] }],
  },
  {
    id: "together-ai",
    name: "Together AI",
    section_id: "gateway-inference-platform",
    short_description: "Hosted inference for open models.",
    preview: "Inference API",
    models: [{ model_id: "together-ai/inference", model_name: "Together Inference", short_description: "Hosted open-model inference endpoint.", tags: ["inference", "open-models"] }],
  },
  {
    id: "replicate",
    name: "Replicate",
    section_id: "gateway-inference-platform",
    short_description: "Model hosting and inference marketplace.",
    preview: "Prediction API",
    models: [{ model_id: "replicate/predictions", model_name: "Replicate Predictions", short_description: "Run hosted community and proprietary models.", tags: ["inference", "marketplace"] }],
  },
  {
    id: "fireworks-ai",
    name: "Fireworks AI",
    section_id: "gateway-inference-platform",
    short_description: "Fast hosted inference stack.",
    preview: "Serverless inference",
    models: [{ model_id: "fireworks-ai/serverless", model_name: "Fireworks Serverless", short_description: "Low-latency hosted inference API.", tags: ["inference", "latency"] }],
  },
  {
    id: "huggingface",
    name: "HuggingFace",
    section_id: "gateway-inference-platform",
    short_description: "Hosted inference and model hub APIs.",
    preview: "Inference Endpoints",
    models: [{ model_id: "huggingface/inference-endpoint", model_name: "HF Inference Endpoint", short_description: "Managed endpoints for hub models.", tags: ["inference", "hub"] }],
  },
  {
    id: "azure-ai-foundry",
    name: "Azure AI Foundry",
    section_id: "gateway-inference-platform",
    short_description: "Azure model hosting and governance layer.",
    preview: "Enterprise platform",
    models: [{ model_id: "azure-ai-foundry/hosted-models", model_name: "Azure AI Foundry Models", short_description: "Enterprise model deployment and policy controls.", tags: ["enterprise", "governance"] }],
  },
  {
    id: "aws-bedrock",
    name: "AWS Bedrock",
    section_id: "gateway-inference-platform",
    short_description: "Managed FM access on AWS.",
    preview: "Bedrock runtime",
    models: [{ model_id: "aws-bedrock/bedrock-runtime", model_name: "Bedrock Runtime", short_description: "Invoke foundation models via managed AWS API.", tags: ["cloud", "enterprise"] }],
  },
  {
    id: "google-vertex-ai",
    name: "Google Vertex AI",
    section_id: "gateway-inference-platform",
    short_description: "Google Cloud model and ML serving platform.",
    preview: "Vertex endpoints",
    models: [{ model_id: "google-vertex-ai/prediction", model_name: "Vertex Prediction", short_description: "Managed model serving and GenAI APIs.", tags: ["cloud", "serving"] }],
  },
  {
    id: "nvidia-nim",
    name: "NVIDIA NIM",
    section_id: "gateway-inference-platform",
    short_description: "Optimized microservices for model inference.",
    preview: "NIM microservices",
    models: [{ model_id: "nvidia-nim/nim-service", model_name: "NIM Service", short_description: "GPU-optimized inferencing microservice.", tags: ["gpu", "inference"] }],
  },
  {
    id: "baseten",
    name: "Baseten",
    section_id: "gateway-inference-platform",
    short_description: "Model deployment and realtime inference.",
    preview: "Truss deployment",
    models: [{ model_id: "baseten/truss", model_name: "Baseten Truss", short_description: "Deploy and scale custom model services.", tags: ["deployment", "inference"] }],
  },
  {
    id: "modal",
    name: "Modal",
    section_id: "gateway-inference-platform",
    short_description: "Serverless compute for AI inference pipelines.",
    preview: "Modal Functions",
    models: [{ model_id: "modal/modal-functions", model_name: "Modal Functions", short_description: "Run model inference as scalable serverless jobs.", tags: ["serverless", "compute"] }],
  },
  {
    id: "runpod",
    name: "RunPod",
    section_id: "gateway-inference-platform",
    short_description: "GPU cloud and serverless endpoints.",
    preview: "Serverless GPU",
    models: [{ model_id: "runpod/serverless", model_name: "RunPod Serverless", short_description: "GPU-backed serverless inference endpoints.", tags: ["gpu", "serverless"] }],
  },
  {
    id: "octoai",
    name: "OctoAI",
    section_id: "gateway-inference-platform",
    short_description: "Inference optimization and serving platform.",
    preview: "Octo inference",
    models: [{ model_id: "octoai/inference", model_name: "OctoAI Inference", short_description: "Managed model serving optimized for throughput.", tags: ["inference", "serving"] }],
  },
  {
    id: "banana-dev",
    name: "Banana.dev",
    section_id: "gateway-inference-platform",
    short_description: "Simple model API hosting.",
    preview: "Banana model endpoint",
    models: [{ model_id: "banana-dev/model-endpoint", model_name: "Banana Endpoint", short_description: "Hosted model inference endpoint.", tags: ["inference", "api"] }],
  },
  {
    id: "portkey",
    name: "Portkey",
    section_id: "gateway-inference-platform",
    short_description: "AI gateway, guardrails and observability.",
    preview: "Gateway + guardrails",
    models: [{ model_id: "portkey/ai-gateway", model_name: "Portkey AI Gateway", short_description: "Unified gateway with policy and logging layers.", tags: ["gateway", "guardrails"] }],
  },
  {
    id: "helicone",
    name: "Helicone",
    section_id: "gateway-inference-platform",
    short_description: "Open-source LLM observability and caching proxy.",
    preview: "Observability proxy",
    models: [{ model_id: "helicone/proxy", model_name: "Helicone Proxy", short_description: "Track, cache and monitor LLM requests.", tags: ["observability", "proxy"] }],
  },
  {
    id: "langdock",
    name: "Langdock",
    section_id: "gateway-inference-platform",
    short_description: "Enterprise AI gateway with policy controls.",
    preview: "Enterprise gateway",
    models: [{ model_id: "langdock/gateway", model_name: "Langdock Gateway", short_description: "Control and route enterprise LLM usage.", tags: ["enterprise", "gateway"] }],
  },
  {
    id: "eden-ai",
    name: "Eden AI",
    section_id: "gateway-inference-platform",
    short_description: "Unified API over multiple AI providers.",
    preview: "Unified API",
    models: [{ model_id: "eden-ai/unified-api", model_name: "Eden AI Unified API", short_description: "Single API surface over many providers.", tags: ["aggregation", "gateway"] }],
  },
  {
    id: "aiproxy",
    name: "AIProxy",
    section_id: "gateway-inference-platform",
    short_description: "Routing, caching and governance proxy for LLM traffic.",
    preview: "Proxy routing",
    models: [{ model_id: "aiproxy/proxy", model_name: "AIProxy Route", short_description: "Policy-aware route for LLM providers.", tags: ["proxy", "routing"] }],
  },
  {
    id: "groqcloud",
    name: "GroqCloud",
    section_id: "gateway-inference-platform",
    short_description: "Ultra-low latency model inference platform.",
    preview: "Low latency inference",
    models: [{ model_id: "groqcloud/chat", model_name: "GroqCloud Chat", short_description: "Fast token throughput model serving endpoint.", tags: ["latency", "inference"] }],
  },
  {
    id: "deepinfra",
    name: "DeepInfra",
    section_id: "gateway-inference-platform",
    short_description: "Hosted inference for open models.",
    preview: "Open model hosting",
    models: [{ model_id: "deepinfra/inference", model_name: "DeepInfra Inference", short_description: "Managed inference for OSS model catalog.", tags: ["inference", "open-models"] }],
  },
  {
    id: "anyscale",
    name: "Anyscale",
    section_id: "gateway-inference-platform",
    short_description: "Ray-based serving and model endpoints.",
    preview: "Ray Serve",
    models: [{ model_id: "anyscale/ray-serve", model_name: "Anyscale Ray Serve", short_description: "Serve and scale LLM endpoints with Ray.", tags: ["serving", "ray"] }],
  },
  {
    id: "inference-net",
    name: "Inference.net",
    section_id: "gateway-inference-platform",
    short_description: "Inference routing and provider abstraction.",
    preview: "Inference routing",
    models: [{ model_id: "inference-net/router", model_name: "Inference.net Router", short_description: "Unified endpoint to multiple model backends.", tags: ["routing", "gateway"] }],
  },
  {
    id: "jina-ai",
    name: "Jina AI",
    section_id: "gateway-inference-platform",
    short_description: "Search/inference APIs for retrieval and agents.",
    preview: "Embeddings + retrieval",
    models: [{ model_id: "jina-ai/embeddings-v3", model_name: "Jina Embeddings v3", short_description: "Embedding endpoint for retrieval pipelines.", tags: ["embeddings", "rag"] }],
  },
  {
    id: "vercel",
    name: "Vercel",
    section_id: "gateway-inference-platform",
    short_description: "AI Gateway and SDK integrations.",
    preview: "Vercel AI Gateway",
    models: [{ model_id: "vercel/ai-gateway", model_name: "Vercel AI Gateway", short_description: "Managed gateway for multi-provider model access.", tags: ["gateway", "developer"] }],
  },
  {
    id: "langfuse",
    name: "Langfuse",
    section_id: "gateway-inference-platform",
    short_description: "LLM observability and evaluation platform.",
    preview: "Tracing + evals",
    models: [{ model_id: "langfuse/observability", model_name: "Langfuse Observability", short_description: "Trace and evaluate model interactions.", tags: ["observability", "evals"] }],
  },
  {
    id: "humanloop",
    name: "Humanloop",
    section_id: "gateway-inference-platform",
    short_description: "Prompt management and eval platform.",
    preview: "PromptOps",
    models: [{ model_id: "humanloop/promptops", model_name: "Humanloop PromptOps", short_description: "Prompt management and experimentation APIs.", tags: ["promptops", "evals"] }],
  },
  {
    id: "galileo-ai",
    name: "Galileo AI",
    section_id: "gateway-inference-platform",
    short_description: "LLM quality monitoring and observability.",
    preview: "Quality monitoring",
    models: [{ model_id: "galileo-ai/monitor", model_name: "Galileo Monitor", short_description: "Monitor model quality, drift and reliability.", tags: ["quality", "observability"] }],
  },

  {
    id: "litellm",
    name: "LiteLLM",
    section_id: "universal-ai-api",
    short_description: "Unified SDK/router for many LLM providers.",
    preview: "SDK + routing",
    models: [{ model_id: "litellm/proxy", model_name: "LiteLLM Proxy", short_description: "Open-source proxy with unified OpenAI-style interface.", tags: ["sdk", "routing", "proxy"] }],
  },
  {
    id: "langchain",
    name: "LangChain",
    section_id: "universal-ai-api",
    short_description: "Application framework for LLM chains and tools.",
    preview: "Agent framework",
    models: [{ model_id: "langchain/core", model_name: "LangChain Core", short_description: "Core abstractions for tools, prompts and models.", tags: ["agent-framework", "orchestration"] }],
  },
  {
    id: "llamaindex",
    name: "LlamaIndex",
    section_id: "universal-ai-api",
    short_description: "RAG and indexing framework for LLM apps.",
    preview: "RAG framework",
    models: [{ model_id: "llamaindex/framework", model_name: "LlamaIndex Framework", short_description: "Indexing and retrieval orchestration for LLM apps.", tags: ["rag", "orchestration"] }],
  },
  {
    id: "autogen",
    name: "AutoGen",
    section_id: "universal-ai-api",
    short_description: "Multi-agent orchestration framework.",
    preview: "Multi-agent",
    models: [{ model_id: "autogen/framework", model_name: "AutoGen Framework", short_description: "Conversation-driven multi-agent execution.", tags: ["agent-framework", "multi-agent"] }],
  },
  {
    id: "crewai",
    name: "CrewAI",
    section_id: "universal-ai-api",
    short_description: "Role-based agent orchestration framework.",
    preview: "Agent crews",
    models: [{ model_id: "crewai/framework", model_name: "CrewAI Framework", short_description: "Coordinate role-based agents and task pipelines.", tags: ["agent-framework", "orchestration"] }],
  },
  {
    id: "langgraph",
    name: "LangGraph",
    section_id: "universal-ai-api",
    short_description: "Graph-based control flow for agent systems.",
    preview: "Graph orchestration",
    models: [{ model_id: "langgraph/runtime", model_name: "LangGraph Runtime", short_description: "Stateful graph execution for advanced agents.", tags: ["orchestration", "graph"] }],
  },
  {
    id: "superagi",
    name: "SuperAGI",
    section_id: "universal-ai-api",
    short_description: "Open-source autonomous agent framework.",
    preview: "Autonomous agents",
    models: [{ model_id: "superagi/platform", model_name: "SuperAGI Platform", short_description: "Agent workflows with plugin and tool integration.", tags: ["agent-framework", "automation"] }],
  },
  {
    id: "vllm",
    name: "vLLM",
    section_id: "universal-ai-api",
    short_description: "High-throughput inference engine for LLM serving.",
    preview: "Inference engine",
    models: [{ model_id: "vllm/server", model_name: "vLLM OpenAI Server", short_description: "OpenAI-compatible server over vLLM runtime.", tags: ["inference-engine", "serving"] }],
  },
  {
    id: "sglang",
    name: "SGLang",
    section_id: "universal-ai-api",
    short_description: "Structured generation and efficient serving stack.",
    preview: "Structured generation",
    models: [{ model_id: "sglang/runtime", model_name: "SGLang Runtime", short_description: "Runtime optimized for structured generation workloads.", tags: ["inference-engine", "structured-output"] }],
  },
  {
    id: "ollama",
    name: "Ollama",
    section_id: "universal-ai-api",
    short_description: "Local model runtime with simple API.",
    preview: "Local runtime",
    models: [{ model_id: "ollama/local", model_name: "Ollama Local API", short_description: "Run and serve local models via HTTP API.", tags: ["local", "runtime"] }],
  },
  {
    id: "localai",
    name: "LocalAI",
    section_id: "universal-ai-api",
    short_description: "Open-source local OpenAI-compatible API server.",
    preview: "OpenAI-compatible local",
    models: [{ model_id: "localai/server", model_name: "LocalAI Server", short_description: "Serve GGUF and other local model formats.", tags: ["local", "openai-compatible"] }],
  },
  {
    id: "haystack",
    name: "Haystack",
    section_id: "universal-ai-api",
    short_description: "Open-source framework for RAG pipelines.",
    preview: "RAG orchestration",
    models: [{ model_id: "haystack/pipeline", model_name: "Haystack Pipeline", short_description: "Composable RAG and retrieval pipeline framework.", tags: ["rag", "orchestration"] }],
  },
  {
    id: "semantic-kernel",
    name: "Semantic Kernel",
    section_id: "universal-ai-api",
    short_description: "Microsoft SDK for AI orchestration and plugins.",
    preview: "SDK + orchestration",
    models: [{ model_id: "semantic-kernel/sdk", model_name: "Semantic Kernel SDK", short_description: "Orchestrate prompts, planners and plugin tools.", tags: ["sdk", "orchestration"] }],
  },
  {
    id: "routellm",
    name: "RouteLLM",
    section_id: "universal-ai-api",
    short_description: "Open-source model router for cost/quality balancing.",
    preview: "Routing",
    models: [{ model_id: "routellm/router", model_name: "RouteLLM Router", short_description: "Route requests to best model under policy.", tags: ["routing", "cost-optimization"] }],
  },
  {
    id: "modelscope-agent",
    name: "ModelScope Agent",
    section_id: "universal-ai-api",
    short_description: "Agent framework ecosystem from ModelScope.",
    preview: "Agent toolkit",
    models: [{ model_id: "modelscope-agent/framework", model_name: "ModelScope Agent Framework", short_description: "Build tool-using agent workflows.", tags: ["agent-framework", "tool-use"] }],
  },
];

interface ExtraModelStore {
  [providerId: string]: CatalogModel[];
}

const globalStore = globalThis as unknown as {
  __ironcoreCatalogExtraModels?: ExtraModelStore;
};

if (!globalStore.__ironcoreCatalogExtraModels) {
  globalStore.__ironcoreCatalogExtraModels = {};
}

function normalize(input: string) {
  return input.trim().toLowerCase();
}

export function listProviders() {
  return baseProviders.map((provider) => ({ ...provider, models: [...provider.models, ...(globalStore.__ironcoreCatalogExtraModels?.[provider.id] ?? [])] }));
}

export function getProvider(providerId: string) {
  const target = normalize(providerId);
  return listProviders().find((provider) => provider.id === target || normalize(provider.name) === target);
}

export function listSectionsSummary() {
  const providers = listProviders();
  return CATALOG_SECTIONS.map((section) => ({
    id: section.id,
    title: section.title,
    description: section.description,
    providers: providers
      .filter((provider) => provider.section_id === section.id)
      .map((provider) => ({
        provider_id: provider.id,
        provider_name: provider.name,
        preview: provider.preview,
        short_description: provider.short_description,
        models_endpoint: `/api/ai-catalog/models?provider=${encodeURIComponent(provider.id)}&page=1`,
      })),
  }));
}

export function queryProviderModels(providerId: string, page: number, filter: string) {
  const provider = getProvider(providerId);
  if (!provider) {
    return null;
  }

  const normalizedFilter = normalize(filter);
  const filteredModels = !normalizedFilter
    ? provider.models
    : provider.models.filter((model) => {
        const haystacks = [
          model.model_id,
          model.model_name,
          model.short_description,
          String(model.context_window ?? ""),
          model.tags.join(" "),
        ]
          .join(" ")
          .toLowerCase();
        return haystacks.includes(normalizedFilter);
      });

  const total = filteredModels.length;
  const safePage = Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
  const totalPages = Math.max(1, Math.ceil(total / AI_CATALOG_PAGE_SIZE));
  const start = (Math.min(safePage, totalPages) - 1) * AI_CATALOG_PAGE_SIZE;
  const models = filteredModels.slice(start, start + AI_CATALOG_PAGE_SIZE);

  return {
    provider,
    models,
    pagination: {
      page: Math.min(safePage, totalPages),
      page_size: AI_CATALOG_PAGE_SIZE,
      total_items: total,
      total_pages: totalPages,
      has_next: Math.min(safePage, totalPages) < totalPages,
      has_prev: Math.min(safePage, totalPages) > 1,
    },
  };
}

export function validateModelId(modelId: string) {
  return /^[a-z0-9][a-z0-9-]*\/[a-z0-9][a-z0-9._-]*$/i.test(modelId.trim());
}

export function addProviderModel(providerId: string, modelId: string, modelName?: string) {
  const provider = getProvider(providerId);
  if (!provider) {
    return { ok: false as const, message: "Provider does not exist in local catalog." };
  }

  if (!validateModelId(modelId)) {
    return { ok: false as const, message: "Invalid model_id. Expected format: provider/model_name." };
  }

  const exists = provider.models.some((model) => normalize(model.model_id) === normalize(modelId));
  if (exists) {
    return { ok: false as const, message: "Model already exists for this provider." };
  }

  const pendingModel: CatalogModel = {
    model_id: modelId.trim(),
    model_name: modelName?.trim() || modelId.split("/")[1],
    short_description: "Pending metadata - will be updated once agent fetches metadata.",
    tags: ["pending-metadata"],
  };

  const current = globalStore.__ironcoreCatalogExtraModels?.[provider.id] ?? [];
  globalStore.__ironcoreCatalogExtraModels = {
    ...(globalStore.__ironcoreCatalogExtraModels ?? {}),
    [provider.id]: [pendingModel, ...current],
  };

  return {
    ok: true as const,
    message: "Model added locally; will update once agent fetches metadata.",
    model: pendingModel,
  };
}

export function buildCatalogMarkdown() {
  const lines: string[] = [];
  const sections = listSectionsSummary();

  lines.push("# AI Provider Catalog");
  lines.push("");
  lines.push(`last_updated: ${AI_CATALOG_LAST_UPDATED}`);
  lines.push("");
  lines.push("## TOC");
  sections.forEach((section) => {
    lines.push(`- [${section.title}](#${section.id})`);
  });
  lines.push("");

  sections.forEach((section) => {
    lines.push(`## ${section.title}`);
    lines.push(`<a id=\"${section.id}\"></a>`);
    lines.push("");
    lines.push(section.description);
    lines.push("");

    section.providers.forEach((provider) => {
      lines.push(`### Provider: ${provider.provider_name}`);
      lines.push(`> ${provider.short_description}`);
      lines.push(`[👉 View models for ${provider.provider_name}](${provider.models_endpoint})`);
      lines.push("");
    });
  });

  lines.push("## Integration Guide");
  lines.push("How to integrate: expose endpoint /models?provider=Meta&page=1&filter=... returning JSON above");
  lines.push("Web update options available");

  return lines.join("\n");
}
