# IronCore: Advanced AI Agent Architecture & Capabilities

IronCore is a highly scalable, event-driven AI orchestration platform designed with a strong focus on autonomous agents, browser stealth automation, code intelligence, and context optimization.

## 1. Core Architecture & Infrastructure

The system is built on a robust, async-first Python backend with a decoupled, modern web control-plane.

### 1.1 Backend Core & Operations
- **Async-First Execution:** Fully asynchronous I/O utilizing `asyncio`, FastAPI, and `aiosqlite`. Ensures non-blocking operations for database queries, network dispatching, and queue draining.
- **Event-Driven Orchestration:** Employs a deterministic Cron Scheduler (APScheduler) for persistent job lifecycles and a Webhook Server with signature verification and replay protection.
- **Dynamic Plugin System:** Extensible runtime environment with AST-based security scanning before loading plugins. Supports dynamic hot-reloading and sandboxing execution (gVisor/Docker).
- **OTA Updates & Mesh Coordination:** Built-in Over-The-Air (OTA) update manager with auto-rollback capabilities, alongside multi-node mesh discovery for distributed deployments (targetting Kubernetes/Helm).
- **Abuse Control:** Community-first safeguards including session/tab throttling, in-memory rate limiting, and anti-spam countermeasures.

### 1.2 Frontend Control-Plane & Terminal
- **Web UI Stack:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS v4, Zustand, and TanStack Query.
- **Real-Time Responsiveness:** Uses WebSockets and Server-Sent Events (SSE) for token-by-token generation logs, tool execution status, and live telemetry data.
- **Console-Based TUI:** An interactive Terminal Setup Assistant that provides human-readable flows and machine-readable JSON outputs for rapid local bootstrapping.

---

## 2. Advanced Agent Capabilities

IronCore delegates tasks to specialized autonomous modules, each exhibiting unique technical traits.

### 2.1 Browser Automation Engine (Stealth & Interaction)
- **Stealth Initialization:** Injects scripts via Playwright to spoof `navigator.webdriver` and bypass elementary bot detections.
- **Hardware & Network Spoofing:** Spoofs WebGL/Canvas APIs using Linear Congruential Generator (LCG) noise to create unique hardware fingerprints. Aligns JA3/TLS headers to match the target OS.
- **Biometric Simulation (Human-like Behavior):** 
  - Calculates mouse trajectories using **Cubic Bezier Curves**.
  - Applies **Fitts's Law** to control movement timing based on target distance and width.
  - Implements Gaussian-distributed typing delays and deliberate cursor overshoot/micro-jitters.
- **AI-Driven CAPTCHA Solving:** Uses OpenCV (Template Matching, Canny Edge Detection) for basic slider CAPTCHAs, and bridges visual inputs to Vision-Language Models (VLMs like Gemini Flash) to solve visual grid CAPTCHAs by determining precise (X,Y) click coordinates.

### 2.2 The Brain (Context & Memory Optimizer)
- **Semantic Caching:** Integrates `sentence-transformers` and ChromaDB to intercept semantically identical queries, bypassing LLM processing entirely to save costs.
- **Prompt KV-Cache:** Exploits prompt caching (`ephemeral` cache controls) to reuse static system instructions, significantly reducing Time To First Token (TTFT).
- **Token Compression & Filtering:** Uses advanced algorithms like LLMLingua to compress RAG context before LLM injection, eliminating stop words while maintaining information entropy.
- **Infinite Context via Sliding Windows:** Prevents context window overflows. When tokens reach a critical threshold, the oldest segments are extracted and condensed into an abstractive summary by a local model (e.g., Llama 3).
- **Model Context Protocol (MCP):** Implements an independent MCP Server handling JSON-RPC 2.0 over SSE, standardizing access to tools and resources for external clients.
- **Autonomous Cost Optimization:** Engine capable of tracking dynamic model utilization and performing automated downgrades during high-burn periods.

### 2.3 Self-Healing LSP Engine (Code Intelligence)
- **Autonomous Code Repair:** Implements a diagnostic-driven healing loop. When the engine detects a syntax or execution error via AST parsing, it consults the LLM, parses the Unified Diff response, and patches the code safely.
- **Safe Edit Rollbacks:** Validates AST integrity before committing files. If diagnostics continue to fail, the system automatically rolls backward to the last healthy state to prevent logic corruption.

---

## 3. Engineering Patterns & Technologies Used

- **Languages & Runtimes:** Python 3.13+, Node.js 22+.
- **Data Modeling:** Pydantic V2 ensures strict typing, validation, and immutable data structures across API endpoints.
- **Database & State:** SQLite via `aiosqlite` with `WAL` journaling mode for concurrent reads/writes without blocking the async event loop.
- **Dependency Injection:** Applied universally across API routers for isolating components during testing.
- **Testing:** Comprehensive test suite utilizing `pytest` and `pytest-asyncio` covering happy paths, security constraints, and failure degradations.
- **Fail-Safe Design:** Employs circuit breakers, exponential backoff/retries, and graceful degradation layers.

---

## 4. Setup & Execution

### Option 1: Local Python
```bash
python -m pip install -r requirements.txt
python -m pip install -e .[dev]
uvicorn ironcore.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### Option 2: Using Makefile
```bash
make install
make run-api
```

### Option 3: Docker Compose
```bash
docker compose up --build
```

**API Health Check:**
```bash
curl http://127.0.0.1:8000/health
```

---

## 5. Testing & Linting
```bash
make test
make test-cov
make lint
make format
```
If your environment lacks `pytest`, `ruff`, `mypy`, or `docker`, please run `make install` first.
