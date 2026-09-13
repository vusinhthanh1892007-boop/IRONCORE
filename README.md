# IronCore

[![CI](https://github.com/vusinhthanh1892007-boop/IRONCORE/actions/workflows/ci.yml/badge.svg)](https://github.com/vusinhthanh1892007-boop/IRONCORE/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.12 | 3.13](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Tests: 1,146 passing](https://img.shields.io/badge/tests-1%2C146%20passing-brightgreen.svg)](https://github.com/vusinhthanh1892007-boop/IRONCORE/actions)

An AI-Agent & Red-Team Security Engineering Platform with Defense Controls. It combines offensive browser automation modeling with defensive enterprise guardrails, human-in-the-loop dual control, and observability.

---

## What is IronCore?

IronCore bridges AI agent execution with practical security engineering. Built with a dual red-team / blue-team architecture:
- **Red-Team & Simulation Engine**: Models how autonomous agents interact with web applications, evaluate bot detection boundaries, and spoof browser fingerprints.
- **Enterprise Defense Controls**: Implements strict defense mechanisms including fail-closed LLM guardrails, true 4-eyes Maker-Checker approval, data loss prevention (DLP), and air-gap network boundaries.

You can operate IronCore via:
- **Web UI**: Modern dashboard built with Next.js and Tailwind CSS.
- **Terminal (TUI)**: Fast console assistant for setup and headless environments.
- **MCP Server**: Model Context Protocol (MCP 2.x) tools ready for Claude Desktop, Cursor, or external LLM orchestrators.

---

## Architecture & Features

### 1. Agent Engine & Red-Team Tooling
- Runs multi-step tasks with streaming progress and token optimization.
- **Biometric Mouse Engine**: Computes realistic Bezier cursor trajectories based on Fitts's law, acceleration curves, and random overshoot.
- **Full Fingerprint Spoofer**: Injects PRNG noise across Canvas, WebGL, AudioContext, Battery, and hardware concurrency vectors.
- **Empirical Stealth Benchmark**: Evaluates browser stealth evasion against standard detection heuristics.

#### Empirical Anti-Bot Evasion Benchmark (`RFC-BOT-HEURISTIC-V1`)
| Detection Vector | Vanilla Playwright | IronCore Stealth Spoofer |
| :--- | :---: | :---: |
| `navigator.webdriver` | DETECTED ❌ (`webdriver=true`) | **PASS ✅** (`webdriver=undefined`) |
| `webgl.unmasked_renderer` | DETECTED ❌ (`SwiftShader / Mesa`) | **PASS ✅** (`Apple M2 / NVIDIA`) |
| `canvas.noise_injection` | DETECTED ❌ (Static fingerprint hash) | **PASS ✅** (PRNG entropy injection) |
| `audio.frequency_drift` | DETECTED ❌ (Zero oscillator jitter) | **PASS ✅** (Micro-channel drift) |
| `window.chrome_runtime` | DETECTED ❌ (Missing runtime object) | **PASS ✅** (Native Chrome descriptor) |
| `hardware.concurrency_memory`| DETECTED ❌ (0GB memory / headless) | **PASS ✅** (8GB normalized memory) |
| **Heuristic Evasion Rate** | **0.0%** (0/6 passed) | **100.0%** (6/6 passed) |

### 2. Enterprise Defense & Safety Controls
- **Fail-Closed Guardrails**: Fast regex/keyword rules paired with an LLM judge. Configured with a strict `fail_closed=True` policy to block/flag requests if the LLM judge times out or encounters network failure, preventing adversarial fail-open bypass.
- **4-Eyes Human-in-the-Loop (HITL)**: `MakerCheckerEngine` enforcing dual-control authorization. Tickets requiring multi-approver sign-off (`required_approvals >= 2`) remain pending until distinct authorized checkers sign with HMAC-SHA256 tokens. Separation of duties prevents the maker (`requestor_id`) from approving their own request.
- **Data Loss Prevention (DLP)**: Scans and masks credit card numbers (validated via Luhn algorithm), emails, and telephone numbers.
- **Air-Gap Network Guard**: Enforces strict outbound CIDR whitelist filtering.
- **Cost & Context Optimizer**: Prompt caching, KV cache, and semantic cache tracking token savings.

### 3. Model Context Protocol (MCP 2.x)
- Built-in standalone MCP server (`mcp_server.py`) using STDIO transport with zero machine-specific dependencies.
- Exposes 9 standardized tools:
  - `dlp_scan_and_mask`: Detect and mask PII.
  - `guardrail_evaluate_prompt`: Evaluate safety rules with fail-closed protection.
  - `calculate_biometric_mouse_path`: Generate human-like Bezier cursor coordinates.
  - `get_captcha_tile_coordinate`: Calculate click coordinates on grid challenges.
  - `calculate_llm_cost_and_savings`: Track token expenditure and cache savings.
  - `airgap_verify_destination`: Verify destination IP against allowed CIDR networks.
  - `hitl_submit_action`: Submit critical actions to the 4-eyes approval queue.
  - `diagnose_python_code_ast`: Inspect Python code for AST syntax and security flaws.
  - `get_stealth_defense_scripts`: Retrieve fingerprint protection scripts.

### 5. Web Dashboard
- Chat interface with live token streaming.
- Management pages for nodes, sessions, cron tasks, audit logs, and security policies.
- Built-in interface language selector supporting 30 languages.

---

## Quickstart

### Requirements
- Python 3.11 or higher
- Node.js 18 or higher (Node 22 recommended)

### 1. Clone the Repository

```bash
git clone https://github.com/vusinhthanh1892007-boop/IRONCORE.git
cd IRONCORE
```

### 2. Set up the Python Backend

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .

# Start the API server
python3 -m uvicorn ironcore.api.server:app --host 127.0.0.1 --port 8000
```

The API will be available at `http://127.0.0.1:8000`. You can check server health at:
```bash
curl http://127.0.0.1:8000/health
```

### 3. Set up the Web Dashboard

```bash
cd web

# Install npm packages
npm install

# Start development server
npm run dev
```

Open `http://localhost:3000` in your web browser. Default local login:
- **Email:** `admin@ironcore.ai`
- **Password:** `admin`

---

## Using the MCP Server

You can connect IronCore to any tool that supports the Model Context Protocol (like Claude Desktop or Cursor).

Add this configuration to your client settings (for example, `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ironcore": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/ironcore-community/mcp_server.py"],
      "env": {
        "IRONCORE_EDITION": "enterprise"
      }
    }
  }
}
```

Now your AI assistant can call IronCore's DLP scanner, mouse calculator, cost tracker, and code diagnostic tools directly.

---

## Project Structure

```text
.
├── ironcore/               # Core Python engine
│   ├── api/                # FastAPI routes (chat, HITL, SIEM, IAM, forensics)
│   ├── browser/            # Playwright automation and evasion scripts
│   ├── core/               # Engine coordinator and context optimizer
│   ├── enterprise/         # DLP, guardrails, airgap, budget, and forensics
│   ├── lsp/                # Code diagnostic and AST repair tools
│   ├── monitoring/         # Metrics collector and incident detection
│   └── tools/              # Built-in agent tools (web search, weather, etc.)
├── web/                    # Next.js web application
│   ├── src/app/            # App Router pages and internal API routes
│   ├── src/components/     # UI components, layout, and language selector
│   └── src/lib/            # Client state, settings, and offline translations
├── skills/                 # Agent skill packs (crypto, weather, browser, etc.)
├── tests/                  # Pytest test suite (1,146 unit tests passing)
├── mcp_server.py           # Standalone Model Context Protocol server
└── pyproject.toml          # Python project settings
```

---

## Configuration

You can configure IronCore using environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `IRONCORE_EDITION` | `community` | Set to `enterprise` to enable enterprise modules. |
| `IRONCORE_API_KEY` | `dev-key` | API key for authenticating backend requests. |
| `IRONCORE_DATA_DIR` | `/tmp/ironcore_data` | Folder where local SQLite databases are saved. |
| `IRONCORE_AIRGAP_ALLOWED_CIDRS` | `10.0.0.0/8,192.168.0.0/16,172.16.0.0/12` | Allowed CIDR ranges for the network guard. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL used by the web dashboard. |

---

## Testing

Run the Python test suite:
```bash
PYTHONPATH=. pytest tests/
```

Check TypeScript types and build the web dashboard:
```bash
cd web
npm run build
```

---

## License

This project is licensed under the MIT License.
