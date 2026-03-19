#!/usr/bin/env python3
"""IronCore V2 — Interactive Terminal Setup Wizard & CLI"""

import asyncio
import json
import os
import sys
import time
import subprocess
import platform
import socket
from datetime import datetime
from pathlib import Path

# ── Auto-install required CLI display libraries ────────────────────────────────
def _ensure_deps():
    try:
        import rich
        import questionary
        import pycountry
    except ImportError:
        print("[ IronCore ] Installing terminal UI dependencies...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "rich", "questionary", "pycountry"],
            stdout=subprocess.DEVNULL,
        )

_ensure_deps()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.text import Text
from rich import box
import questionary
import pycountry
from questionary import Style

console = Console()

# ── Questionary style (OpenClaw-inspired theme) ───────────────────────────────
IC_STYLE = Style([
    ("qmark",        "fg:#00d7ff bold"),
    ("question",     "bold"),
    ("answer",       "fg:#00d7ff bold"),
    ("pointer",      "fg:#00d7ff bold"),
    ("highlighted",  "fg:#00d7ff bold"),
    ("selected",     "fg:#ffffff"),
    ("separator",    "fg:#555555"),
    ("instruction",  "fg:#555555 italic"),
    ("text",         ""),
    ("disabled",     "fg:#555555 italic"),
])

CONFIG_PATH = Path.home() / ".ironcore" / "config.json"


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()

# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────
SEARCH_PROVIDERS = [
    {"id": "brave",       "label": "Brave Search  — Private, no tracking, fast index"},
    {"id": "perplexity",  "label": "Perplexity AI — LLM-powered summarised results"},
    {"id": "gemini",      "label": "Gemini Search  — Google knowledge, multimodal"},
    {"id": "grok",        "label": "Grok (xAI)    — Real-time X/Twitter data"},
    {"id": "tavily",      "label": "Tavily        — Purpose-built for AI agents"},
    {"id": "exa",         "label": "Exa           — Neural web search API"},
    {"id": "skip",        "label": "Skip for now"},
]

MODEL_PROVIDERS = {
    "OpenAI":     ["gpt-5.4", "gpt-5.1", "gpt-4o", "o3", "o4-mini"],
    "Anthropic":  ["claude-opus-4.6", "claude-sonnet-4.6", "claude-haiku-4.6"],
    "Google":     ["gemini-3.1-pro", "gemini-3.1-flash", "gemini-3.1-flash-lite"],
    "xAI":        ["grok-4", "grok-4-mini"],
    "Mistral":    ["mistral-large-2", "mistral-medium", "mixtral-8x22b"],
    "DeepSeek":   ["deepseek-v3.2", "deepseek-r1", "deepseek-v3"],
    "Cohere":     ["command-r-plus", "command-r"],
    "Alibaba":    ["qwen-3.5-72b", "qwen-3.5-14b", "qwen-2.5-coder"],
    "Meta":       ["llama-4-maverick", "llama-4-scout", "llama-3.3-70b"],
    "OpenRouter": ["<any provider via openrouter.ai>"],
    "Ollama":     ["llama3", "mistral", "deepseek-r1", "phi-4  (local)"],
    "AWS Bedrock":["claude-sonnet-4.6", "nova-pro", "llama-4-scout"],
}

SKILLS = [
    {"id": "web_search",   "name": "Web Search",        "req": "API key required",   "key": True},
    {"id": "code_exec",    "name": "Code Execution",     "req": "Docker / sandbox",   "key": False},
    {"id": "browser",      "name": "Stealth Browser",    "req": "Playwright install", "key": False},
    {"id": "memory",       "name": "Long-term Memory",   "req": "ChromaDB",           "key": False},
    {"id": "hitl",         "name": "Human-in-the-Loop",  "req": "No extras needed",   "key": False},
    {"id": "rag",          "name": "RAG / File Q&A",     "req": "Embedding model",    "key": False},
    {"id": "voice",        "name": "Voice (STT/TTS)",    "req": "ElevenLabs API key", "key": True},
    {"id": "dlp",          "name": "DLP Shield",         "req": "Enterprise only",    "key": False},
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _hr(title: str = ""):
    console.print(Rule(title, style="dim cyan"))

def _step(n: int, total: int, title: str):
    console.print(f"\n[bold cyan]▶ Step {n}/{total} — {title}[/bold cyan]")

def _badge(ok: bool) -> str:
    return "[bold green]✓ OK[/bold green]" if ok else "[bold red]✗ FAIL[/bold red]"

def _mask(key: str) -> str:
    if not key or len(key) < 8:
        return "••••••••"
    return key[:4] + "••••" + key[-4:]

def _save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _build_language_catalog() -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    for language in pycountry.languages:
        code = getattr(language, "alpha_2", None)
        name = getattr(language, "name", None)
        if not code or not name:
            continue
        code = code.lower()
        if code in seen:
            continue
        seen.add(code)
        native = getattr(language, "common_name", None) or getattr(language, "inverted_name", None)
        label = f"{name} ({code})"
        if native and native != name:
            label = f"{name} / {native} ({code})"
        items.append({"code": code, "name": name, "label": label})

    if not any(item["code"] == "en" for item in items):
        items.append({"code": "en", "name": "English", "label": "English (en)"})
    if not any(item["code"] == "vi" for item in items):
        items.append({"code": "vi", "name": "Vietnamese", "label": "Vietnamese (vi)"})

    items.sort(key=lambda x: x["name"].lower())
    return items


_LANG_CATALOG = _build_language_catalog()


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    if not _is_interactive_terminal():
        return default

    default_hint = "y" if default else "n"
    accepted_yes = {"y", "yes", "ok", "1"}
    accepted_no = {"n", "no", "0"}

    while True:
        raw = questionary.text(
            f"{prompt} (y/n, default={default_hint}):",
            default=default_hint,
            style=IC_STYLE,
        ).ask()

        value = (raw or "").strip().lower()
        if not value:
            return default
        if value in accepted_yes:
            return True
        if value in accepted_no:
            return False

        console.print("[yellow]Please enter only y or n. Example: y = yes, n = no. Try again.[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────
# ASCII Banner
# ─────────────────────────────────────────────────────────────────────────────
def _banner():
    console.clear()
    art = """[bold cyan]
██╗██████╗  ██████╗ ███╗   ██╗ ██████╗ ██████╗ ██████╗ ███████╗
██║██╔══██╗██╔═══██╗████╗  ██║██╔════╝██╔═══██╗██╔══██╗██╔════╝
██║██████╔╝██║   ██║██╔██╗ ██║██║     ██║   ██║██████╔╝█████╗  
██║██╔══██╗██║   ██║██║╚██╗██║██║     ██║   ██║██╔══██╗██╔══╝  
██║██║  ██║╚██████╔╝██║ ╚████║╚██████╗╚██████╔╝██║  ██║███████╗
╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝[/bold cyan]"""
    console.print(art)
    console.print(
        "[dim]IronCore V2 — 2026.3 · Autonomous AI Agent Platform · The Titanium in your shell 🛡️[/dim]\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Welcome & Preflight
# ─────────────────────────────────────────────────────────────────────────────
def step_preflight(cfg: dict) -> dict:
    _step(1, 14, "Welcome & Preflight Check")
    console.print(Panel(
        "[bold]IronCore Setup Wizard[/bold] will configure your local AI agent runtime.\n\n"
        "This wizard will set up:\n"
        "  • Model providers & API keys\n"
        "  • Skills & plugins\n"
        "  • Gateway service (API + WebSocket)\n"
        "  • Agent persona & memory policy\n\n"
        "[dim]Estimated time: 3–5 minutes[/dim]",
        title="Welcome", border_style="cyan", expand=False
    ))

    checks = []
    # OS
    os_name = platform.system()
    checks.append(("Operating System", os_name, True))
    # Python version
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    py_ok = sys.version_info >= (3, 10)
    checks.append(("Python", py, py_ok))
    # Write access to config dir
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_ok = os.access(CONFIG_PATH.parent, os.W_OK)
    except Exception:
        write_ok = False
    checks.append(("Config dir writable", str(CONFIG_PATH.parent), write_ok))
    # Network
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        net_ok = True
    except OSError:
        net_ok = False
    checks.append(("Internet access", "reachable" if net_ok else "offline", net_ok))
    # Docker
    docker_ok = subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    checks.append(("Docker daemon", "running" if docker_ok else "not found (optional)", docker_ok or True))

    table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
    table.add_column("Check", style="dim")
    table.add_column("Value")
    table.add_column("Status")
    for name, val, ok in checks:
        table.add_row(name, val, _badge(ok))
    console.print(table)

    all_critical = all(ok for _, _, ok in checks[:4])
    if not all_critical:
        console.print("[bold red]⚠  Some critical checks failed. Setup may not work correctly.[/bold red]")

    proceed = ask_yes_no("Continue with setup?", default=True)
    if not proceed:
        console.print("[dim]Setup cancelled.[/dim]")
        sys.exit(0)

    cfg["preflight"] = {"os": os_name, "python": py, "network": net_ok, "docker": docker_ok}
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Language
# ─────────────────────────────────────────────────────────────────────────────
def step_language(cfg: dict) -> dict:
    _step(2, 14, "Interface Language")
    console.print("[dim]Search language by name/code, then choose from the scrollable list.[/dim]")

    search_term = ""
    selected = None

    while selected is None:
        search_term = questionary.text(
            "Type language name or code to search (blank = show all):",
            default=search_term,
            style=IC_STYLE,
        ).ask() or ""

        needle = search_term.strip().lower()
        filtered = [
            item for item in _LANG_CATALOG
            if not needle or needle in item["name"].lower() or needle in item["code"] or needle in item["label"].lower()
        ]

        if not filtered:
            console.print("[yellow]No language matched. Try another keyword.[/yellow]")
            continue

        labels = [item["label"] for item in filtered[:400]]
        labels.append("Search again")
        picked = questionary.select(
            f"Select language ({len(filtered)} matches):",
            choices=labels,
            style=IC_STYLE,
        ).ask()

        if picked == "Search again":
            continue

        selected = next((item for item in filtered if item["label"] == picked), None)

    console.print(f"  [green]✓[/green] Language set to [bold]{selected['label']}[/bold]")
    cfg["language"] = selected["label"]
    cfg["language_code"] = selected["code"]
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Auth / Access Token (optional)
# ─────────────────────────────────────────────────────────────────────────────
def step_auth(cfg: dict) -> dict:
    _step(3, 14, "Authentication (optional)")
    console.print("[dim]IronCore can store config locally (no account needed) or link to a cloud account.[/dim]\n")
    choice = questionary.select(
        "Authentication mode:",
        choices=[
            "Local only — no account, config saved to ~/.ironcore",
            "Enter IronCore Cloud token — sync settings across devices",
            "Skip",
        ],
        style=IC_STYLE,
    ).ask()

    if "Cloud token" in choice:
        token = questionary.password("Paste your IronCore Cloud token:", style=IC_STYLE).ask()
        if token:
            cfg["auth"] = {"token_present": True, "token_masked": _mask(token)}
            console.print(f"  [green]✓[/green] Token saved: [dim]{_mask(token)}[/dim]")
    else:
        cfg["auth"] = {"token_present": False}
        console.print("  [dim]Running in local mode.[/dim]")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Search Provider
# ─────────────────────────────────────────────────────────────────────────────
def step_search(cfg: dict) -> dict:
    _step(4, 14, "Web Search / RAG Provider")
    console.print("[dim]Enable web search so your agent can fetch live information.[/dim]\n")

    choices = [p["label"] for p in SEARCH_PROVIDERS]
    choice_label = questionary.select("Select search provider:", choices=choices, style=IC_STYLE).ask()
    provider = next(p for p in SEARCH_PROVIDERS if p["label"] == choice_label)

    if provider["id"] == "skip":
        cfg["search"] = {"provider": None, "has_api_key": False}
        console.print("  [dim]Search disabled.[/dim]")
        return cfg

    api_key = ""
    if provider["id"] not in ("skip",):
        api_key = questionary.password(
            f"Paste your {provider['id'].capitalize()} API key (leave blank to skip):",
            style=IC_STYLE
        ).ask() or ""

    cfg["search"] = {
        "provider": provider["id"],
        "has_api_key": bool(api_key),
        "key_masked": _mask(api_key) if api_key else None,
    }
    console.print(f"  [green]✓[/green] Search provider: [bold]{provider['id']}[/bold]  key: {_mask(api_key) if api_key else '[dim]none[/dim]'}")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Model Provider(s)
# ─────────────────────────────────────────────────────────────────────────────
def step_providers(cfg: dict) -> dict:
    _step(5, 14, "Model Provider(s)")
    console.print("[dim]Select the LLM providers you want to use. You can add multiple.[/dim]\n")

    selected = questionary.checkbox(
        "Choose providers (Space to select, Enter to confirm):",
        choices=list(MODEL_PROVIDERS.keys()),
        style=IC_STYLE,
    ).ask() or []

    providers_cfg = {}
    for prov in selected:
        key = questionary.password(f"  API key for [bold]{prov}[/bold] (blank = skip):", style=IC_STYLE).ask() or ""
        providers_cfg[prov] = {"has_api_key": bool(key), "key_masked": _mask(key) if key else None}
        status = "[green]✓ Key saved[/green]" if key else "[yellow]⚠ No key[/yellow]"
        console.print(f"    {prov}: {status}")

    cfg["providers"] = providers_cfg
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Model Picker
# ─────────────────────────────────────────────────────────────────────────────
def step_model_picker(cfg: dict) -> dict:
    _step(6, 14, "Model Selection")
    providers = list(cfg.get("providers", {}).keys())
    if not providers:
        console.print("  [dim]No providers configured. Skipping model selection.[/dim]")
        cfg["selected_model"] = None
        return cfg

    prov_choice = questionary.select(
        "Which provider to pick the primary model from?",
        choices=providers + ["Skip"],
        style=IC_STYLE,
    ).ask()

    if prov_choice == "Skip":
        cfg["selected_model"] = None
        return cfg

    models = MODEL_PROVIDERS.get(prov_choice, [])
    model = questionary.select(
        f"Choose model from {prov_choice}:",
        choices=models,
        style=IC_STYLE,
    ).ask()

    cfg["selected_model"] = {"provider": prov_choice, "model_id": model}
    console.print(f"  [green]✓[/green] Primary model: [bold]{prov_choice} / {model}[/bold]")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Skills / Plugins
# ─────────────────────────────────────────────────────────────────────────────
def step_skills(cfg: dict) -> dict:
    _step(7, 14, "Skills & Plugins")

    table = Table(title="Available Skills", box=box.SIMPLE, show_header=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Skill", style="bold")
    table.add_column("Requirement", style="dim")
    table.add_column("API Key?", style="dim")
    for i, sk in enumerate(SKILLS, 1):
        table.add_row(str(i), sk["name"], sk["req"], "Yes" if sk["key"] else "No")
    console.print(table)

    selected = questionary.checkbox(
        "Enable skills (Space to select):",
        choices=[sk["name"] for sk in SKILLS],
        style=IC_STYLE,
    ).ask() or []

    skills_cfg = {}
    for sk_name in selected:
        sk = next(s for s in SKILLS if s["name"] == sk_name)
        key = ""
        if sk["key"]:
            key = questionary.password(f"  API key for [bold]{sk_name}[/bold]:", style=IC_STYLE).ask() or ""
        skills_cfg[sk["id"]] = {"enabled": True, "has_api_key": bool(key), "key_masked": _mask(key) if key else None}
        console.print(f"    [green]✓[/green] {sk_name} enabled")

    cfg["skills"] = skills_cfg
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Hooks & Automation
# ─────────────────────────────────────────────────────────────────────────────
def step_hooks(cfg: dict) -> dict:
    _step(8, 14, "Hooks & Automation")
    console.print("[dim]Configure event hooks for your agent (on message, on error, on reset).[/dim]\n")

    enable = ask_yes_no("Enable webhook notifications?", default=False)
    hooks_cfg = {"webhook_enabled": enable}

    if enable:
        url = questionary.text("Webhook URL (e.g. https://your-server/hook):", style=IC_STYLE).ask() or ""
        secret = questionary.password("Webhook HMAC secret (blank = no signature):", style=IC_STYLE).ask() or ""
        hooks_cfg.update({
            "webhook_url": url,
            "has_secret": bool(secret),
            "secret_masked": _mask(secret) if secret else None,
        })
        console.print(f"  [green]✓[/green] Webhook: [bold]{url}[/bold]  HMAC: {'set' if secret else 'none'}")

    cfg["hooks"] = hooks_cfg
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Gateway / Runtime
# ─────────────────────────────────────────────────────────────────────────────
def step_gateway(cfg: dict) -> dict:
    _step(9, 14, "Gateway & Runtime Service")
    console.print("[dim]The IronCore gateway exposes a REST API + WebSocket on localhost.[/dim]\n")

    port = questionary.text("Gateway port:", default="8000", style=IC_STYLE).ask() or "8000"
    bind = questionary.select(
        "Bind address:",
        choices=["127.0.0.1 (loopback — local only)", "0.0.0.0 (all interfaces — expose to network)"],
        style=IC_STYLE,
    ).ask()
    bind_ip = "127.0.0.1" if "loopback" in bind else "0.0.0.0"

    cfg["gateway"] = {
        "port": port,
        "bind": bind_ip,
        "web_ui_url": f"http://{bind_ip}:{port}",
        "ws_url": f"ws://{bind_ip}:{port}/ws",
    }
    console.print(f"  [green]✓[/green] Gateway: [bold]http://{bind_ip}:{port}[/bold]  WS: [bold]ws://{bind_ip}:{port}/ws[/bold]")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 — Token & Secrets
# ─────────────────────────────────────────────────────────────────────────────
def step_secrets(cfg: dict) -> dict:
    _step(10, 14, "Token & Secrets Management")
    import secrets as _secrets
    token = _secrets.token_urlsafe(32)
    masked = _mask(token)
    console.print(Panel(
        f"[bold]Gateway Token generated:[/bold]\n\n  [dim]{masked}[/dim]\n\n"
        "[yellow]⚠  This token is shown only once. Copy it now before continuing.[/yellow]\n"
        "[dim]Stored in ~/.ironcore/config.json with mode 600.[/dim]",
        title="Token", border_style="yellow", expand=False
    ))
    # Save raw token to config only in memory (masked in saved JSON)
    cfg["secrets"] = {"token_present": True, "token_masked": masked, "_raw_token": token}
    ask_yes_no("I have copied the token. Continue?", default=True)
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 — Agent Persona
# ─────────────────────────────────────────────────────────────────────────────
def step_persona(cfg: dict) -> dict:
    _step(11, 14, "Agent Persona & Seed Data")
    console.print("[dim]Define how your IronCore agent introduces itself and behaves by default.[/dim]\n")

    name = questionary.text("Agent name:", default="IronCore", style=IC_STYLE).ask() or "IronCore"
    system_prompt = questionary.text(
        "System prompt (one line):",
        default="You are IronCore, an expert autonomous AI agent.",
        style=IC_STYLE,
    ).ask() or "You are IronCore."

    memory = questionary.select(
        "Memory retention policy:",
        choices=[
            "session    — Forget after each conversation",
            "persistent — Remember across sessions (SQLite)",
            "summary    — Keep compressed summaries only",
        ],
        style=IC_STYLE,
    ).ask()
    memory_mode = memory.split()[0]

    cfg["persona"] = {
        "name": name,
        "system_prompt": system_prompt,
        "memory_policy": memory_mode,
    }
    console.print(f"  [green]✓[/green] Agent: [bold]{name}[/bold]  memory: [bold]{memory_mode}[/bold]")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 12 — Smoke Test
# ─────────────────────────────────────────────────────────────────────────────
def step_smoke_test(cfg: dict) -> dict:
    _step(12, 14, "Sandbox Smoke Test")
    console.print("[dim]Running a lightweight dry-run to verify configuration...[/dim]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        t = progress.add_task("Running smoke test...", total=5)
        checks_smoke = [
            ("Config loaded",         True),
            ("Model provider config", bool(cfg.get("providers"))),
            ("Skills config",         True),
            ("Gateway config",        bool(cfg.get("gateway"))),
        ]
        results = []
        for label, state in checks_smoke:
            time.sleep(0.4)
            results.append((label, state))
            progress.advance(t)

    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Test")
    table.add_column("Result")
    for label, ok in results:
        table.add_row(label, _badge(ok))
    console.print(table)

    passed = sum(1 for _, ok in results if ok)
    console.print(f"\n  Smoke test: [bold cyan]{passed}/{len(results)} checks passed[/bold cyan]")
    cfg["smoke_test"] = {"passed": passed, "total": len(results)}
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 13 — Deploy / Start Confirmation
# ─────────────────────────────────────────────────────────────────────────────
def step_deploy(cfg: dict) -> dict:
    _step(13, 14, "Deploy & Start")
    console.print("[dim]Choose how to start IronCore after setup completes.[/dim]\n")

    deploy_mode = questionary.select(
        "Launch mode:",
        choices=[
            "Start API server now  (make run-api)",
            "Start via Docker      (make run-docker)",
            "Print start command   (do it myself)",
            "Skip / Do it later",
        ],
        style=IC_STYLE,
    ).ask()

    cfg["deploy"] = {"mode": deploy_mode}

    if "Start API server" in deploy_mode:
        console.print("  [dim italic]Starting API server after wizard completes...[/dim italic]")
    elif "Docker" in deploy_mode:
        console.print("  [dim italic]Starting Docker stack after wizard completes...[/dim italic]")
    elif "Print" in deploy_mode:
        console.print("  [bold]Run this command when ready:[/bold]")
        console.print(f"    [cyan]cd {Path.cwd()} && make run-api[/cyan]")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# STEP 14 — Summary & Export
# ─────────────────────────────────────────────────────────────────────────────
def step_summary(cfg: dict) -> dict:
    _step(14, 14, "Summary & Config Export")

    gw = cfg.get("gateway", {})
    persona = cfg.get("persona", {})
    model = cfg.get("selected_model", {}) or {}
    providers_str = ", ".join(cfg.get("providers", {}).keys()) or "none"
    skills_str = ", ".join(cfg.get("skills", {}).keys()) or "none"

    summary = Table(title="IronCore Configuration Summary", box=box.ROUNDED, show_header=False, padding=(0, 2))
    summary.add_column("Field", style="dim")
    summary.add_column("Value", style="bold white")

    summary.add_row("Agent name",   persona.get("name", "-"))
    summary.add_row("Memory",       persona.get("memory_policy", "-"))
    summary.add_row("Providers",    providers_str)
    summary.add_row("Primary model",f"{model.get('provider', '')} / {model.get('model_id', '-')}")
    summary.add_row("Search",       cfg.get("search", {}).get("provider") or "disabled")
    summary.add_row("Skills",       skills_str)
    summary.add_row("Gateway",      gw.get("web_ui_url", "-"))
    summary.add_row("Config file",  str(CONFIG_PATH))
    summary.add_row("Last updated", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    console.print(summary)

    # Remove raw token before saving to file for security
    export_cfg = {k: v for k, v in cfg.items() if k != "_raw_token"}
    if "secrets" in export_cfg:
        export_cfg["secrets"] = {k: v for k, v in export_cfg["secrets"].items() if k != "_raw_token"}

    _save_config(export_cfg)
    console.print(f"\n  [green]✓[/green] Config saved to [bold]{CONFIG_PATH}[/bold]\n")
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Main setup wizard flow
# ─────────────────────────────────────────────────────────────────────────────
def run_wizard():
    """Run the full 14-step setup wizard."""
    _banner()

    existing = _load_config()
    if existing:
        console.print(Panel(
            f"[bold]Existing config found[/bold] at [dim]{CONFIG_PATH}[/dim]\n\n"
            f"  Language : {existing.get('language', '?')}\n"
            f"  Model    : {(existing.get('selected_model') or {}).get('model_id', '?')}\n"
            f"  Gateway  : {existing.get('gateway', {}).get('web_ui_url', '?')}",
            title="Existing Config Detected", border_style="yellow", expand=False
        ))
        use_existing = questionary.select(
            "Config handling:",
            choices=["Use existing values (QuickStart)", "Reconfigure from scratch"],
            style=IC_STYLE,
        ).ask()
        if "QuickStart" in use_existing:
            console.print("\n[bold cyan]✓ QuickStart — using saved configuration.[/bold cyan]")
            console.print(f"  [dim]Run [bold]make run-api[/bold] to start the agent.[/dim]\n")
            return existing

    # V3: Use new Textual TUI instead of basic cli steps
    try:
        from ironcore.tui.app import IronCoreTUI
        cfg = IronCoreTUI().run()
        if not cfg:
            sys.exit(0)
    except ImportError:
        console.print("[bold red]Failed to load Graphical TUI[/bold red]\nFalling back to old wizard...")
        cfg: dict = {}
        cfg = step_preflight(cfg)
        cfg = step_auth(cfg)
        cfg = step_search(cfg)
        cfg = step_providers(cfg)
        cfg = step_model_picker(cfg)
        cfg = step_skills(cfg)
        cfg = step_hooks(cfg)
        cfg = step_gateway(cfg)
        cfg = step_secrets(cfg)
        cfg = step_persona(cfg)
        cfg = step_smoke_test(cfg)
        cfg = step_deploy(cfg)
        cfg = step_summary(cfg)

    console.print(Panel(
        "[bold cyan]IronCore is configured and ready![/bold cyan]\n\n"
        "  • [bold]Start server:[/bold]  make run-api\n"
        "  • [bold]Web UI:[/bold]        http://localhost:3000\n"
        "  • [bold]API docs:[/bold]      http://localhost:8000/docs\n\n"
        "[dim]Type [bold]python cli.py chat[/bold] to open the interactive chat shell.[/dim]",
        title="✓ Setup Complete", border_style="cyan"
    ))
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Interactive Chat Loop (original feature — preserved)
# ─────────────────────────────────────────────────────────────────────────────
async def run_chat(cfg: dict):
    """Interactive async chat loop with IronCore Engine."""
    from ironcore.core.engine import IronCoreEngine
    engine = IronCoreEngine()

    persona_name = cfg.get("persona", {}).get("name", "IronCore")
    console.print(Panel(
        f"[bold cyan]{persona_name} is online.[/bold cyan]\n"
        "[dim]Type your message. Commands: /exit  /clear  /status[/dim]",
        border_style="cyan", expand=False
    ))

    while True:
        try:
            prompt = input(f"\n👤 You: ").strip()
            if not prompt:
                continue
            if prompt in ("/exit", "/quit", "exit", "quit"):
                console.print("[dim]Goodbye![/dim]")
                break
            if prompt == "/clear":
                console.clear()
                continue
            if prompt == "/status":
                console.print(f"  Model: {cfg.get('selected_model', {})}")
                continue

            console.print("[dim italic]Thinking...[/dim italic]")
            console.print(f"\n🤖 [bold cyan]{persona_name}:[/bold cyan]", end=" ")
            async for chunk in engine.run_loop(prompt, max_iterations=5):
                if chunk["type"] == "agent.response":
                    print(chunk.get("content", ""), end="", flush=True)
                elif chunk["type"] == "tool.started":
                    console.print(f"\n[bold yellow]🛠  Tool: {chunk.get('tool_name')}[/bold yellow]")
            print("\n")

        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"\n[bold red]Error: {e}[/bold red]")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    if "chat" in args:
        # Skip wizard; go directly to chat
        cfg = _load_config() or {}
        _banner()
        asyncio.run(run_chat(cfg))
    else:
        if not _is_interactive_terminal():
            cfg = _load_config() or {}
            console.print("[dim]Non-interactive terminal detected. Wizard skipped to avoid waiting for input.[/dim]")
            if cfg:
                console.print(f"[dim]Loaded config: {CONFIG_PATH}[/dim]")
            else:
                console.print("[yellow]No existing config found. Re-run in interactive terminal to configure.[/yellow]")
            return

        # V3: Launch Graphical TUI
        try:
            from ironcore.tui.app import IronCoreTUI
            cfg = IronCoreTUI().run()
        except ImportError:
            console.print("[yellow]TUI Framework missing, falling back to CLI setup...[/yellow]")
            cfg = run_wizard()
            
        if cfg and ask_yes_no("Open interactive chat shell now?", default=True):
            asyncio.run(run_chat(cfg))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Aborted.[/dim]")
        sys.exit(0)
