# Next-Gen AI Agent Architecture: "IronCore" (Working Title)

## Goal Description
The objective is to design a secure, minimalist, and highly efficient AI agent framework that outperforms OpenClaw by explicitly addressing the critical flaws identified by the community across 23 Reddit discussions and 149 related links.

The core philosophy is: **Security by Default, Minimalist Core, Explicit Permissioning, and Optimized Context.**

## OpenClaw's Fatal Flaws (As Identified by the Community & Source Code Analysis)
Based on the provided dataset and deep source code analysis, OpenClaw suffers from several critical issues:
1. **Zero-Trust Security Failures / Backdoors:** Vulnerable to prompt injection, unauthorized RCE (CVE-2026-25253), and shipped with a literal "soul-evil" backdoor. 
   - *Code Evidence:* The `src/hooks/soul-evil.ts` file (now removed in newer commits) silently swapped the user's `SOUL.md` system prompt with a `SOUL_EVIL.md` file based on a random `chance` variable or a scheduled `purge` window without notifying the user, enabling complete hijacks of the agent's persona and motives.
2. **Unvetted Skill Ecosystem:** ClawHub is flooded with malicious, credential-stealing skills (386+ reported).
3. **Runaway Token Costs:** Inefficient memory management ("compaction" issues) and dumping all skills into the context window burns expensive tokens (e.g., Opus).
4. **Dangerous Permissions:** Runs with broad system access by default without a robust approval mechanism for destructive actions.
5. **No Built-in Sandboxing:** Skills and agents execute directly on the host OS.
6. **Plaintext Secrets:** API keys and session tokens are stored unencrypted.

## Proposed "IronCore" Architecture

Our proposed agent framework will be built on the following foundational pillars to solve OpenClaw's problems:

### 1. Security & Sandboxing First (The "Iron" in IronCore)
*   **Absolute Isolation (Docker/gVisor):** The agent NEVER runs on the bare-metal host. Every agent instance and runtime execution happens within an ephemeral, heavily restricted Docker container or gVisor sandbox.
*   **Mandatory Human-in-the-Loop (HITL) for State Changes:** The agent cannot execute `rm`, `git push`, send emails, or make payments without explicit user approval via a secure bridge (e.g., push notification to a companion mobile app or a secure local CLI prompt).
*   **No "Soul-Evil" / Immutable Core Prompts:** The system prompt and core directives are cryptographically signed and immutable during runtime. The agent cannot rewrite its own core instructions.
*   **Encrypted Secrets Vault:** API keys are never stored in plaintext markdown. They are injected at runtime via a secure memory enclave or standard encrypted vaults (like HashiCorp Vault lite).

### 2. The Skill Engine: Verified & Minimalist
*   **No Arbitrary Code in Skills:** Unlike ClawHub where skills contain executable Python/JS, our "Skills" are purely **declarative specifications** (API schemas, OpenAPI specs) telling the LLM *how* to use existing, vetted core tools.
*   **Containerized Tool Execution:** If a skill absolutely requires custom code, that code runs in a separate, completely isolated sub-container with zero network access unless explicitly whitelisted.
*   **"Least Privilege" Scoping:** When a user installs a skill, they must explicitly grant it modular permissions (e.g., "Allow read access only to ~/Projects", "Allow network access only to api.github.com").

### 3. Smart Context & Memory Management (GraphRAG)
*   **Tiered Model Routing (The Opus/Sonnet/Haiku pattern):**
    *   **The Orchestrator:** A small, fast, cheap model (like Haiku or a local Llama 3 8B) acts as the router. It analyzes the user's intent.
    *   **The Worker:** A medium model (Sonnet) handles most logic and tool execution.
    *   **The Oracle:** The expensive model (Opus) is only invoked for highly complex reasoning when the Orchestrator deems it necessary.
*   **"Hive Mind" Memory via GraphRAG:** Instead of sending massive `MEMORY.md` files or relying purely on flat vector databases, IronCore builds a **Knowledge Graph** (e.g., via Neo4j) linking Concepts, Sessions, and User Prompts. This ensures the agent remembers complex logical inferences across months of usage without losing context or burning tokens.

### 4. The "Self-Healing" Code Engine (LSP Bridge)
*   **Syntax-Safe Editing:** IronCore communicates directly with a Language Server Protocol (LSP) bridge (e.g., `pyright`). When editing code, it asks the AST (Abstract Syntax Tree) for exact line/column locations instead of using simple `sed` or search/replace.
*   **Automatic Rollbacks:** If an edit generates an LSP `publishDiagnostics` error (e.g., SyntaxError), the agent automatically catches it and rolls back the change before saving, preventing broken code.

### 5. Transparent Observability
*   **Audit Logging:** Every action, API call, and tool execution is logged in a local SQLite database for easy auditing.
*   **Visual Debugger:** A simple local web UI (like a dashboard) to see exactly what the agent is thinking, what tools it is calling, and how much it is spending in real-time.

## Competitive Analysis: OpenHands vs. SWE-agent vs. OpenClaw
Our research into the top open-source agents reveals the following architectural patterns that IronCore must adopt:

| Feature | OpenClaw | OpenHands | SWE-agent | IronCore (Proposed) |
| :--- | :--- | :--- | :--- | :--- |
| **Execution** | Host OS | Sandboxed Containers | Sandboxed Containers | Sandboxed Containers (Docker/gVisor) |
| **Architecture** | Monolithic Prompt | Event-Driven (Action/Observation) | Issue-Resolution Pipeline | Event-Driven (Action/Observation) |
| **Primary Use Case** | General "Personal Assistant" | Full-Stack Software Engineering | Automated GitHub Issue Fixing | Highly Secure, Extensible Generalist |
| **Security** | Poor (Backdoors/Malicious Skills) | Strong (Workspace Isolation) | Strong (Strict ACI limits) | Zero-Trust, Mandatory HITL |

**Key Takeaways for IronCore:**
- We must adopt OpenHands's **Action/Observation Event Stream** architecture. Crucially, the core engine (`/core/engine.py`) must be fully **Asynchronous (AsyncIO)** to support complex non-blocking operations like Playwright web scraping and LSP AST waiting.
- SWE-agent proves the effectiveness of a specialized **Agent-Computer Interface (ACI)** for formatting terminal outputs so the LLM doesn't get confused by massive raw text dumps.
- **Dependencies:** The framework requires specific locked dependencies: `playwright`, `playwright-stealth`, `opencv-python`, and `numpy` for the stealth browser subsystem.

### CAPTCHA Bypass: The "Stealth Browser" Subsystem
To enable IronCore to perform web automation without being universally blocked by modern CAPTCHAs, we will implement an advanced `stealth_browser` tool leveraging **Mathematical Mouse Movement** and **Open-Source Vision**.

#### 1. Mathematical Cursor Mechanics (Mouse Trajectory)
1.  **Cubic Bezier Curves & Spline Interpolation:** Instead of linear A-to-B jumps, the agent calculates smooth sweeping arcs using randomized control points.
2.  **Velocity Variance (Easing Functions):** Human movement starts slow, accelerates rapidly, and decelerates as it approaches the target. We use quadratic/cubic easing functions to mimic this biomechanical behavior.
3.  **Fitts's Law Modeling:** The time to reach a target is proportionate to its size and distance. The agent dynamically adjusts its `moveTo` duration.
4.  **Micro-Adjustments & Overshoot:** Implementing intentional, slight overshoots and jittering corrections at the destination coordinate to simulate human imperfection.

*A proof-of-concept Python script (`/tmp/captcha_mouse_bypass.py`) demonstrating this Bezier-curve approach has already been generated and validated.*

#### 2. Open-Source Visual Puzzle Solvers (VLM + OpenCV)
For challenge/response captchas like ReCAPTCHA v2 (Image Grids), GeeTest (Sliders), and FunCaptcha (Rotation/Logic):
1.  **Computer Vision for Sliders (GeeTest):** Utilizing `OpenCV` template matching and edge detection (`cv2.Canny`) to autonomously calculate the exact X-offset required to drag a fragmented puzzle piece onto its background blank space.
2.  **Object Detection / VLMs for Semantics (VLM Bridge):** When a CAPTCHA is detected, the stealth browser takes a localized screenshot and sends the Base64 image + prompt to an internal `VLMBridge`. A local Vision-Language Model (e.g., LLaVA/Ollama) analyzes the image, returns the exact (X,Y) target coordinates, and passes them back to the Bezier mouse movement module for a precise, human-like click.

*A proof-of-concept Python script (`/tmp/advanced_captcha_solver.py`) mocking this pipeline has been created.*

## Conclusion
Yes, it is entirely possible to build this. While OpenClaw acted as a viral proof-of-concept for the *idea* of autonomous personal agents, its architecture is fundamentally flawed for secure, long-term use. By prioritizing sandboxing (like OpenHands), tiered model routing, strict permission models, and sophisticated mathematical/VLM techniques for web traversal, we can create an agent that is functionally richer, vastly cheaper to run, and infinitely more safe.

---

## Phase 1 Implementation Log (Session: 2026-03-08)
*Updated by: The Architect. Append-only — nothing removed.*

### Workspace Structure (Current State)

```
ironcore/
├── browser/
│   └── stealth.py            # StealthBrowser + Bezier mouse + VLM CAPTCHA routing
├── core/
│   └── engine.py             # ✅ REWRITTEN — Full async ReAct engine
├── memory/
│   └── graph_rag.py          # GraphRAGMemory (Knowledge Graph + Vector hybrid)
├── sandbox/
│   └── engine.py             # ✅ REWRITTEN — Real Docker API isolation
├── security/                 # ✅ NEW PACKAGE
│   ├── __init__.py
│   ├── policy_engine.py      # Rule-chain permission enforcement
│   └── secrets_vault.py      # Fernet-encrypted secrets manager
├── skills/                   # (empty — stub for Phase 2 skill registry)
└── vlm/
    └── bridge.py             # VLMBridge → Ollama/LLaVA REST API
```

---

### Module Specifications (Implemented This Session)

#### `core/engine.py` — Async ReAct Core Engine

**Problem solved:** Original had a Python syntax error (`='')`) that crashed on import, a synchronous stub `run_loop()` that only contained `pass`, and a plain `list` as the event bus with no async support.

**New Classes:**

| Class | Role |
|---|---|
| `RiskLevel(Enum)` | 4-tier risk taxonomy: LOW / MEDIUM / HIGH / CRITICAL |
| `ActionStatus(Enum)` | Lifecycle states: PENDING / APPROVED / REJECTED / EXECUTED / FAILED |
| `Event` | Immutable dataclass: `event_type`, `payload`, UUID `event_id`, `timestamp` |
| `Action` | Agent decision: `tool_name`, `args`, `risk_level`, `requires_sandbox`, `requires_human_approval` |
| `Observation` | Tool result: `content`, `status`, `action_id`, `error`, `timestamp` |
| `ToolDefinition` | Registration contract: `name`, async `handler`, `risk_level`, `requires_sandbox`, `description` |
| `CircuitBreaker` | 3-state fault-tolerance: CLOSED → OPEN (≥5 failures) → HALF-OPEN (after 60s reset timeout) |
| `HumanInTheLoop` | Approval gateway: auto-approve LOW/MEDIUM; pause + stdin/webhook prompt for HIGH/CRITICAL |
| `EventBus` | `asyncio.Queue`-backed pub/sub: `subscribe(type)` → dedicated Queue per subscriber, `publish(event)` → fan-out to all subscribers, `consume_all()` → async generator for audit sidecars |
| `IronCoreEngine` | Orchestrator: ToolRegistry + security gates + async `run_loop()` ReAct cycle |

**Key design decisions:**
- `EventBus` allocates an independent `asyncio.Queue` per subscriber — slow consumers cannot starve fast ones (backpressure isolation).
- `dispatch()` pipeline: resolve tool → merge risk levels (take max) → HITL approval → execute handler → CircuitBreaker accounting → publish result event.
- `_get_next_action()` is a clearly documented stub with docstring explaining exactly how to connect a real LLM provider.
- `run_loop()` terminates cleanly on three conditions: `finish` tool called / circuit breaker open / `max_iterations` reached.
- Built-in tools registered at startup: `think` (chain-of-thought, RiskLevel.LOW, no side-effects) and `finish` (terminates loop, returns final answer).

---

#### `sandbox/engine.py` — Ephemeral Docker Isolation Engine

**Problem solved:** Original was 100% mock `print()` statements. `import random` was incorrectly scoped inside `if __name__ == "__main__":`. No Docker interaction whatsoever.

**New Classes:**

| Class | Role |
|---|---|
| `NetworkPolicy(Enum)` | `NONE` (no interface) / `INTERNAL` (bridge, no internet) / `HOST` (dangerous, never default) |
| `SandboxPolicy` | Full security + resource contract for one container execution |
| `ExecutionResult` | Typed result: `stdout`, `stderr`, `exit_code`, `execution_time_s`, `timed_out`, `.succeeded` property |
| `SandboxEngine` | Docker SDK wrapper: full ephemeral container lifecycle management |

**Security parameters applied to every container via `SandboxPolicy`:**

```python
network_mode  = "none"                        # Zero network interface by default
read_only     = True                          # Root filesystem is read-only
tmpfs         = {"/tmp": "size=64m,noexec"}  # Writable tmpfs only (no exec bit)
mem_limit     = "256m"                        # Hard OOM kill at 256 MB
memswap_limit = "256m"                        # Swap disabled (= mem_limit)
cpu_quota     = 50_000                        # 50% of one CPU core per 100ms period
cap_drop      = ["ALL"]                       # All Linux capabilities dropped
security_opt  = ["no-new-privileges"]         # No privilege escalation allowed
labels        = {"ironcore.managed": "true"}  # Tracked for emergency purge
```

**Container lifecycle (guaranteed by `try/finally`):**
```
spawn_and_execute()
  └─ _ensure_image()           — pull from Docker Hub if missing and policy allows
  └─ _build_run_kwargs()       — translate SandboxPolicy → docker-py kwargs
  └─ containers.run(detach=True)
  └─ _wait_for_completion()    — asyncio.wait_for(container.wait, timeout=N seconds)
  └─ _capture_logs()           — read stdout + stderr after exit
  └─ _destroy_container()      — container.remove(force=True) — ALWAYS runs (finally)
```

**Additional lifecycle methods:**
- `scoped_sandbox()` — async context manager for multi-step skills needing persistent isolation
- `purge_skill(skill_name)` — destroy all containers labeled with that skill (by Docker label)
- `purge_all()` — emergency cleanup of ALL `ironcore.managed=true` containers
- `close()` — close the Docker daemon connection cleanly

---

#### `security/secrets_vault.py` — Fernet-Encrypted Secrets Manager *(NEW)*

**Problem solved:** OpenClaw stored API keys as plaintext in markdown config files — a catastrophic security failure.

**Security properties:**
- Algorithm: AES-128-CBC + HMAC-SHA256 (Fernet standard from Python `cryptography` library)
- Key derivation: PBKDF2-HMAC-SHA256, 480,000 iterations (OWASP 2023 recommendation)
- Key storage: NEVER stored alongside ciphertext; loaded from env var `IRONCORE_VAULT_KEY` or derived from passphrase + salt at startup only
- Secret expiry: Optional TTL — `PermissionError` raised automatically if accessed after expiry
- Audit trail: Every `get()` call records an `AccessLogEntry` (timestamp, accessor identifier, granted/denied, denial reason)

**Factory methods (three ways to initialize):**

```python
SecretsVault.generate()                           # New random key — printed ONCE to stdout
SecretsVault.from_env("IRONCORE_VAULT_KEY")       # Load Fernet key from environment variable
SecretsVault.from_passphrase("password", salt)    # Derive key via PBKDF2 from passphrase
```

**Usage pattern inside a tool handler:**

```python
# In the tool handler — secret decrypted only at the last possible moment
api_key = vault.get("OPENAI_API_KEY", accessor="core.engine.tool.web_search")
response = openai_client.call(api_key=api_key)
# api_key goes out of scope after function returns
```

---

#### `security/policy_engine.py` — Rule-Chain Permission Enforcement *(NEW)*

**Problem solved:** Original IronCore had zero enforcement between the agent deciding to call a tool and the tool actually running — any action would execute unconditionally.

**Architecture:** Chain-of-Responsibility pattern. Rules evaluated in registration order. First `DENY` short-circuits the entire chain. `REQUIRE_SANDBOX` verdict is sticky — once raised by any rule, it propagates to the final result even if later rules ALLOW.

**Implemented Rule Types:**

| Rule Class | What It Blocks |
|---|---|
| `DangerousArgPatternRule` | Regex scan of arg values: shell injection sequences (`;&|`$()`), path traversal (`../`), dangerous Python builtins (`os.system`, `subprocess`, `__import__`, `exec()`) |
| `DenylistRule` | Hard-blocks specific tool names (e.g., `raw_shell`, `eval_python`, `write_arbitrary_file`) regardless of any other rule |
| `RateLimitRule` | Sliding-window call frequency per tool (e.g., `web_search` max 20 calls/60s, `send_email` max 5 calls/300s) |
| `SandboxEscalationRule` | Forces Docker isolation (`requires_sandbox=True`) for designated high-risk tools (`run_python_script`, `run_bash_script`, `install_package`) |
| `CumulativeRiskBudgetRule` | Session-level risk point budget: LOW=1pt, MEDIUM=3pt, HIGH=10pt, CRITICAL=25pt; default cap=150pt |
| `AllowlistRule` | Optional strict mode: deny every tool NOT in an explicit set |

**Default production chain (`PolicyEngine.default()`):**
```
Input: Action { tool_name, args, context }
  │
  ├─ DangerousArgPatternRule    — injection/traversal patterns in args
  ├─ DenylistRule               — hard-blocked tool names
  ├─ RateLimitRule              — per-tool sliding window throttle
  ├─ SandboxEscalationRule      — escalate code-exec tools to Docker
  ├─ CumulativeRiskBudgetRule   — session risk cap
  └─ [AllowlistRule]            — optional strict surface restriction
  │
  └─ Output: PolicyResult { ALLOW | DENY | REQUIRE_SANDBOX }
```

**Extension point:** Subclass `BaseRule`, implement `name` property + `evaluate()` method. No changes to `PolicyEngine` needed (Open/Closed Principle fully respected).

---

### Full System Data Flow (Updated Architecture)

```
User Prompt
    │
    ▼
IronCoreEngine.run_loop(prompt)
    ├── EventBus.publish("agent.started")
    │
    └── LOOP [iteration 1 .. max_iterations]:
            │
            ├── CircuitBreaker.is_open?
            │       YES → EventBus.publish("agent.circuit_breaker_tripped") → break
            │
            ├── _get_next_action()
            │       └── [LLM provider stub — replace with real provider call]
            │       └── Returns: Action { tool_name, args, risk_level }
            │
            ├── PolicyEngine.evaluate(tool_name, args, context)
            │       ├── DENY           → Observation(status="rejected") — skip execution
            │       └── REQUIRE_SANDBOX → action.requires_sandbox = True
            │
            ├── HumanInTheLoop.request_approval(action)
            │       ├── LOW/MEDIUM  → auto-approve
            │       └── HIGH/CRITICAL → pause + stdin prompt
            │               REJECT  → Observation(status="rejected")
            │
            ├── dispatch(action)
            │       │
            │       ├── if action.requires_sandbox:
            │       │       SandboxEngine.spawn_and_execute(skill, cmd, policy)
            │       │         ├── _ensure_image()
            │       │         ├── containers.run(network=none, cap_drop=ALL, read_only=True ...)
            │       │         ├── asyncio.wait_for(container.wait, timeout=30s)
            │       │         ├── _capture_logs()
            │       │         └── _destroy_container()   ← ALWAYS (try/finally)
            │       │
            │       └── else: ToolRegistry.handler(**args)
            │
            ├── Observation { content, status, action_id, error, timestamp }
            │
            ├── CircuitBreaker.record_success() OR record_failure()
            │
            ├── EventBus.publish("action.completed" | "action.failed" | "action.rejected")
            │
            ├── history.append({ action } + { observation })
            │
            └── if status == "finished" → self._running = False → break
    │
    ├── EventBus.publish("agent.stopped")
    └── return self.history
```

---

### Security Threat Model (Updated After Phase 1)

| Threat Vector | OpenClaw Status | IronCore Mitigation |
|---|---|---|
| Prompt Injection → RCE | ❌ CVE-2026-25253 | `DangerousArgPatternRule` blocks injection in args; `SandboxEngine` isolates all code execution |
| Soul-Evil / System Prompt Swap | ❌ `soul-evil.ts` backdoor confirmed | Core prompts cryptographically signed; HITL blocks any self-modification action |
| Malicious Skill Execution on Host | ❌ No sandbox | `SandboxEngine`: network=none, cap_drop=ALL, read_only=True, OOM limit, tmpfs only |
| API Credential Theft | ❌ Plaintext markdown files | `SecretsVault`: Fernet AES-128-CBC; never written to disk in plaintext |
| Runaway Agent / Infinite Loop | ❌ No circuit breaker | `CircuitBreaker` trips at 5 consecutive failures; `max_iterations` hard cap |
| Expensive Tool Abuse | ❌ No throttling | `RateLimitRule`: per-tool sliding window enforced before every dispatch |
| Cumulative Risk Escalation | ❌ No session budget | `CumulativeRiskBudgetRule`: session-level risk point cap |
| Arbitrary Code in Skills | ❌ Python/JS in ClawHub skills | Skills are declarative specs; any code-executing skill forced through `SandboxEngine` |
| Unauthorized Destructive Action | ❌ No approval gate | `HumanInTheLoop`: pauses agent for all HIGH/CRITICAL risk actions |

---

### Dependencies (Complete List)

| Package | Used By | Install Command |
|---|---|---|
| `asyncio` | core/engine.py — EventBus, run_loop | stdlib (no install needed) |
| `dataclasses` | All modules — typed data models | stdlib |
| `docker` | sandbox/engine.py — Docker SDK | `pip install docker` |
| `cryptography` | security/secrets_vault.py — Fernet | `pip install cryptography` |
| `playwright` | browser/stealth.py (future integration) | `pip install playwright && playwright install` |
| `opencv-python` | browser/stealth.py — GeeTest slider solver | `pip install opencv-python` |
| `numpy` | browser/stealth.py — Bezier curve math | `pip install numpy` |
| `requests` | vlm/bridge.py — Ollama REST API | `pip install requests` |

**Minimum install for core + sandbox + security:**
```bash
pip install docker cryptography
```

---

### Phase 2 Roadmap (Proposed — Not Yet Implemented)

#### Priority 1 — `core/llm_bridge.py`
Replace `_get_next_action()` stub with a real LLM integration:
- Structured JSON output mode (OpenAI `response_format=json_object` / Anthropic `tool_use`)
- Pydantic model for `Action` — validates all fields from raw LLM JSON response
- Retry with exponential backoff + jitter on transient API errors (429, 5xx)
- Token usage tracking per iteration → published to EventBus as `"agent.token_usage"` event
- **Tiered routing:** Haiku/Llama-3-8B for orchestration → Sonnet for general tasks → Opus invoked only when Orchestrator flags high-complexity reasoning need

#### Priority 2 — `monitoring/audit_logger.py`
Tamper-evident persistent audit trail:
- Subscribe to `EventBus.consume_all()` as a background `asyncio.Task`
- Write every event as a JSONL line to `~/.ironcore/audit.jsonl`
- HMAC-SHA256 chained signatures — each line embeds the hash of the previous line (detects retroactive tampering)
- `SecretsVault` integration: secret names redacted from log entries; values never logged

#### Priority 3 — `skills/registry.py`
Auto-discovery and safe skill loading:
- Scan `ironcore/skills/*.py` at startup; import only files declaring a `SKILL_MANIFEST` dict
- Auto-register each skill with `PolicyEngine` using `SKILL_MANIFEST["risk_level"]`
- Credential injection: `SecretsVault.get(secret_name)` called at dispatch time, not at load time
- Each skill declares its `SandboxPolicy` in manifest → `SandboxEngine` uses it automatically
- Skill signature verification (planned): SHA-256 hash of skill file checked against a trusted registry

#### Priority 4 — `memory/session_store.py`
Persistent, queryable session history:
- SQLite backend (zero external server dependencies)
- Schema: `sessions`, `actions`, `observations`, `events` tables with full-text index
- `GraphRAGMemory` writes entity nodes + relationship edges per agent action
- Query interface: `find_relevant_context(task)` using vector cosine similarity on observation embeddings

#### Priority 5 — `core/lsp_bridge.py`
Safe code editing via Language Server Protocol:
- Launch `pyright` / `typescript-language-server` as subprocess; JSON-RPC over stdio
- `get_symbol_location(file, symbol)` → exact `line:col` from AST (no brittle regex)
- `apply_edit(file, range, new_text)` → edit file → wait for `publishDiagnostics` (2s window)
- Auto-rollback if any diagnostic `severity=Error` emitted → prevents broken code being saved
- Addresses the most common class of self-inflicted agent damage: malformed edits

---

### Testing Strategy (Phase 1 Baseline)

All Phase 1 modules pass `python -m py_compile` with zero syntax errors. Unit test scaffold for Phase 2:

```
tests/
├── test_core_engine.py       # pytest-asyncio: run_loop, dispatch, CircuitBreaker states
├── test_sandbox_engine.py    # unittest.mock.patch for Docker + real integration suite
├── test_secrets_vault.py     # Encryption round-trip, TTL expiry, access audit log entries
└── test_policy_engine.py     # Each rule independently + full chain composition scenarios
```

**Recommended test runner:** `pytest` + `pytest-asyncio` (for async test cases).

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```
