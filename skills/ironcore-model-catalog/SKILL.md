---
name: ironcore-model-catalog
description: Browse the latest AI models available on OpenRouter — names, providers, context size, pricing. No login needed for public catalog.
metadata: {"openclaw": {"emoji": "🤖", "requires": {"bins": ["python3", "curl"]}}}
---

# IronCore Model Catalog

Query the OpenRouter model catalog to see what AI models are available, their context lengths, pricing, and providers.

## When to use
- User asks "what models are available?", "which is cheapest?", "list all Claude/GPT/Gemini models"
- User wants to compare model context sizes or pricing
- User wants to find a free or cheap model for a task

## How to run

```bash
curl -s --max-time 15 "https://openrouter.ai/api/v1/models" -o /tmp/openrouter_models.json && python3 << 'EOF'
import json, sys

with open('/tmp/openrouter_models.json') as f:
    data = json.load(f)

models = data.get('data', [])
if not models:
    print("Could not fetch models. Check internet connection.")
    sys.exit(1)

print(f"Total models available: {len(models)}\n")

# Filter and display by provider
FILTER = ""  # REPLACE with provider name to filter: "anthropic", "openai", "google", "meta-llama", "deepseek", etc.

shown = 0
for m in sorted(models, key=lambda x: x.get('id', '')):
    mid = m.get('id', '')
    if FILTER and FILTER.lower() not in mid.lower():
        continue
    ctx = m.get('context_length', 0)
    pricing = m.get('pricing', {})
    prompt_price = float(pricing.get('prompt', 0)) * 1_000_000
    name = m.get('name', mid)
    print(f"{mid:<55} ctx:{ctx//1000:>4}k  \${prompt_price:.3f}/M tokens")
    shown += 1
    if shown >= 30:
        print(f"... and {len(models) - shown} more. Set FILTER to narrow results.")
        break
EOF
```

## Steps
1. Run the command above to fetch the live catalog
2. If user asks for a specific provider, replace `FILTER = ""` with the provider name
3. Summarize the most relevant models based on what the user needs
4. Highlight free models (price = 0) vs paid ones

## Common provider filter values
- `anthropic` → Claude models
- `openai` → GPT models  
- `google` → Gemini models
- `meta-llama` → LLaMA models
- `deepseek` → DeepSeek models
- `mistralai` → Mistral models
- `qwen` → Alibaba Qwen models
- `free` → models with ":free" in their ID

## Error handling
If curl returns an error (exit code 6 = no network), inform the user that OpenRouter may be unreachable from the current network and suggest checking internet connectivity.
