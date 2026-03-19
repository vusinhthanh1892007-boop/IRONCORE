# IronCore 🛡️
**Next-Generation Secure AI Agent Framework**

> Vượt trội OpenClaw về mọi mặt: Bảo mật, Hiệu năng, Vượt CAPTCHA, & Chi phí Token.

---

## Cấu trúc Dự án

```
ironcore/
├── api/              # REST API server + authentication
├── browser/          # Stealth Browser + CAPTCHA Bypass (Playwright + OpenCV)
├── core/             # Async ReAct Engine + LLM Router + Entity Extractor
├── lsp/              # Language Server Protocol Bridge (Self-Healing Code)
├── memory/           # GraphRAG "Hive Mind" Memory (Neo4j + ChromaDB)
├── monitoring/       # Tamper-evident Audit Logger (HMAC-chained JSONL)
├── sandbox/          # Docker Isolation Engine (Least-Privilege Containers)
├── security/         # Policy Engine + Secrets Vault + RBAC
├── skills/           # Declarative Skill Registry
├── tests/            # pytest + pytest-asyncio test suite
└── vlm/              # Vision-Language Model Bridge (LLaVA / Ollama)
```

## Cài đặt

```bash
pip install -r requirements.txt
playwright install chromium
```

## Chạy tests

```bash
pytest tests/ -v
```

## Agents được phân công

| Module | Agent |
|---|---|
| `core/`, `sandbox/`, `security/` | GPT-5.4 (The Architect) |
| `memory/`, `vlm/`, `core/llm_bridge.py` | Claude 4.6 (The Brain) |
| `browser/` | Gemini 3.1 Pro (The Ghost) |
