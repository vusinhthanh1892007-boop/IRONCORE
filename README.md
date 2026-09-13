# IronCore

A runtime and web control panel for AI agents. It combines browser automation, developer tools, security guards, and a multi-language dashboard into a single codebase.

---

## What is IronCore?

IronCore lets you run autonomous tasks locally or on a server. It connects large language models to everyday developer workflows like browsing websites, editing code, scanning text for sensitive information, and managing LLM costs.

You can control IronCore using:
- **Web UI**: A modern dashboard built with Next.js and Tailwind CSS.
- **Terminal (TUI)**: A console assistant for fast command-line setup.
- **MCP Server**: Standard Model Context Protocol tools you can plug into Claude Desktop, Cursor, or other MCP clients.

---

## Features

### 1. Agent Engine & Tools
- Runs tasks step-by-step with streaming progress.
- Includes built-in tools for web search, file editing, Python AST checks, and weather lookups.
- Works with cloud providers (OpenAI, Anthropic, Google Gemini) and local models (Ollama, vLLM, LocalAI).

### 2. Browser Automation
- Uses Playwright to load web pages and collect information.
- Simulates human mouse movements with Bezier curves and typing delays.
- Includes coordinate helpers for grid-based CAPTCHA tasks.

### 3. Model Context Protocol (MCP)
- Built-in MCP 2.x server (`mcp_server.py`) using STDIO transport.
- Exposes 9 tools directly to MCP-enabled tools:
  - `dlp_scan_and_mask`: Detect and mask emails, phone numbers, and credit cards.
  - `guardrail_evaluate_prompt`: Check prompts against security rules.
  - `calculate_biometric_mouse_path`: Generate human-like cursor coordinates.
  - `get_captcha_tile_coordinate`: Calculate click targets on grid images.
  - `calculate_llm_cost_and_savings`: Track token costs and prompt caching savings.
  - `airgap_verify_destination`: Verify if an IP or domain matches allowed networks.
  - `hitl_submit_action`: Send risky actions to a human approval queue.
  - `diagnose_python_code_ast`: Find syntax errors and examine functions in Python code.
  - `get_stealth_defense_scripts`: Inspect browser fingerprint protection scripts.

### 4. Security & Enterprise Guards
- **Data Loss Prevention (DLP)**: Masks credit card numbers (with Luhn validation), email addresses, and Vietnam phone numbers before sending data to models.
- **Prompt Guardrails**: Checks incoming prompts for prompt injection and blocked keywords.
- **Human-in-the-Loop (HITL)**: Holds sensitive actions in a pending queue until an operator approves or rejects them.
- **AirGap Network Guard**: Restricts outbound connections to allowed CIDR network ranges.
- **Budget Tracking**: Tracks token usage by model and calculates cost savings from caching.

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
├── tests/                  # Pytest test suite (1000+ unit tests)
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
