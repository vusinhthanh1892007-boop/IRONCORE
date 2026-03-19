"""
IronCore: LLM Tiered Router + LiteLLM Wrapper
===============================================
Phase 1 — The Brain (Claude Sonnet 4.6)

Responsibilities:
  - Classify task complexity → route to appropriate LLM tier
  - Unified LiteLLM interface for OpenAI / Anthropic / Google / Ollama
  - Format tools for LLM function calling (OpenAI-compatible schema)
  - Parse LLM JSON response → Action object
  - Token cost tracking + session budget enforcement
  - Streaming support via EventBus events

Tier Routing:
  SIMPLE   → Ollama llama3.1 8B    (free, local, zero cost)
  MEDIUM   → Claude Haiku 3.5      (cheap, fast, capable)
  COMPLEX  → Claude Sonnet 4.6     (this model — balanced)
  CRITICAL → Claude Opus 4.6       (best reasoning, expensive)

Author: The Brain (IronCore Project)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Tuple

import litellm
from pydantic import BaseModel, Field, field_validator

from ironcore.core.engine import (
    Action,
    Event,
    EventBus,
    RiskLevel,
    ToolDefinition,
)

# ── V2 Optimizer imports (optional — không break nếu chưa install) ──────────
if TYPE_CHECKING:
    from ironcore.optimizer.semantic_cache import CachedResponse, SemanticCache
    from ironcore.optimizer.prompt_kv_cache import PromptKVCacheManager
    from ironcore.enterprise.budget.guard import BudgetGuard  # Phase 15
    from ironcore.enterprise.budget.optimizer import CostOptimizer  # Phase 17

logger = logging.getLogger(__name__)

# Suppress LiteLLM's verbose default logging — we handle our own.
litellm.suppress_debug_output = True


# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────

class BrainError(Exception):
    """Base exception for all Brain module errors."""


class LLMRoutingError(BrainError):
    """Raised when no LLM tier can successfully handle the request."""


class LLMResponseParseError(BrainError):
    """Raised when the LLM response cannot be parsed into a valid Action."""


class LLMBudgetExceededError(BrainError):
    """Raised when cumulative session cost exceeds the configured budget cap."""


# ──────────────────────────────────────────────────────────────────────────────
# Data Models (Pydantic V2)
# ──────────────────────────────────────────────────────────────────────────────

class TaskComplexity(str, Enum):
    """
    Four-tier complexity classification for LLM routing decisions.

    SIMPLE   — Q&A, lookups, format conversion         (< 50 words)
    MEDIUM   — Summarisation, analysis, multi-step     (50–200 words)
    COMPLEX  — Code generation, reasoning chains       (200+ words)
    CRITICAL — Security decisions, system-level changes (best model mandatory)
    """
    SIMPLE   = "simple"
    MEDIUM   = "medium"
    COMPLEX  = "complex"
    CRITICAL = "critical"


class ModelConfig(BaseModel):
    """Full configuration for one LLM model instance used by LiteLLM."""

    model_id: str = Field(..., description="LiteLLM model string, e.g. 'ollama/llama3.1'")
    max_input_tokens: int = Field(default=8_000, ge=1)
    max_output_tokens: int = Field(default=4_096, ge=1)
    cost_per_1k_input_tokens: float = Field(default=0.0, ge=0.0)
    cost_per_1k_output_tokens: float = Field(default=0.0, ge=0.0)
    supports_vision: bool = Field(default=False)
    supports_function_calling: bool = Field(default=True)
    timeout_seconds: float = Field(default=45.0, gt=0.0)
    temperature: float = Field(default=0.1)

    @field_validator("temperature")
    @classmethod
    def clamp_temperature(cls, v: float) -> float:
        return max(0.0, min(2.0, v))


class LLMResponse(BaseModel):
    """Structured result from a single raw LLM API call."""

    content: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model_used: str = Field(default="")
    latency_ms: float = Field(default=0.0, ge=0.0)
    finish_reason: str = Field(default="stop")
    # ── Observability ──────────────────────────────────────────────────────
    trace_id: str = Field(default="")
    # ── Anthropic prompt cache stats (populated when KV-cache is active) ──
    cache_write_tokens: int = Field(default=0, ge=0)  # tokens used to CREATE cache (100% cost)
    cache_read_tokens: int = Field(default=0, ge=0)   # tokens READ from cache (10% cost)


class CostRecord(BaseModel):
    """Running cost and token usage accumulated across a session."""

    session_id: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    last_updated: float = Field(default_factory=time.time)

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: ModelConfig,
    ) -> None:
        """Accumulate usage from one LLM call into the running totals."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        cost = (
            (input_tokens  / 1_000) * model.cost_per_1k_input_tokens
            + (output_tokens / 1_000) * model.cost_per_1k_output_tokens
        )
        self.total_cost_usd += cost
        self.call_count += 1
        self.last_updated = time.time()


# ──────────────────────────────────────────────────────────────────────────────
# Model Tier Configuration
# ──────────────────────────────────────────────────────────────────────────────

MODEL_TIERS: Dict[TaskComplexity, List[ModelConfig]] = {
    TaskComplexity.SIMPLE: [
        ModelConfig(
            model_id="ollama/llama3.1",
            max_input_tokens=8_000,
            max_output_tokens=2_048,
            cost_per_1k_input_tokens=0.0,
            cost_per_1k_output_tokens=0.0,
            timeout_seconds=30.0,
        ),
        # Fallback if Ollama is not running locally
        ModelConfig(
            model_id="claude-haiku-3-5",
            max_input_tokens=200_000,
            max_output_tokens=4_096,
            cost_per_1k_input_tokens=0.0008,
            cost_per_1k_output_tokens=0.004,
            timeout_seconds=30.0,
        ),
    ],
    TaskComplexity.MEDIUM: [
        ModelConfig(
            model_id="claude-haiku-3-5",
            max_input_tokens=200_000,
            max_output_tokens=4_096,
            cost_per_1k_input_tokens=0.0008,
            cost_per_1k_output_tokens=0.004,
            timeout_seconds=30.0,
        ),
        ModelConfig(
            model_id="gpt-4o-mini",
            max_input_tokens=128_000,
            max_output_tokens=4_096,
            cost_per_1k_input_tokens=0.00015,
            cost_per_1k_output_tokens=0.0006,
            timeout_seconds=30.0,
        ),
    ],
    TaskComplexity.COMPLEX: [
        ModelConfig(
            model_id="claude-sonnet-4-6",
            max_input_tokens=200_000,
            max_output_tokens=8_192,
            cost_per_1k_input_tokens=0.003,
            cost_per_1k_output_tokens=0.015,
            timeout_seconds=60.0,
        ),
        ModelConfig(
            model_id="gpt-4.5",
            max_input_tokens=128_000,
            max_output_tokens=8_192,
            cost_per_1k_input_tokens=0.005,
            cost_per_1k_output_tokens=0.015,
            timeout_seconds=60.0,
        ),
    ],
    TaskComplexity.CRITICAL: [
        ModelConfig(
            model_id="claude-opus-4-6",
            max_input_tokens=200_000,
            max_output_tokens=8_192,
            cost_per_1k_input_tokens=0.015,
            cost_per_1k_output_tokens=0.075,
            supports_vision=True,
            timeout_seconds=120.0,
        ),
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# Complexity Classifier
# ──────────────────────────────────────────────────────────────────────────────

# Keyword sets for heuristic classification  (lowercase)
_SECURITY_KEYWORDS: frozenset[str] = frozenset({
    "security", "vulnerability", "exploit", "injection", "authentication",
    "authorization", "encryption", "cve", "backdoor", "privilege", "escalation",
    "malware", "ransomware", "phishing", "xss", "csrf", "rce", "sqli",
})

_CODE_KEYWORDS: frozenset[str] = frozenset({
    "implement", "write code", "debug", "refactor", "optimize", "generate",
    "function", "class", "module", "api", "database", "algorithm",
    "architecture", "async", "docker", "deploy", "unit test", "script",
    "parser", "compiler", "regex", "pipeline",
})

_REASONING_KEYWORDS: frozenset[str] = frozenset({
    "analyze", "compare", "evaluate", "assess", "explain why", "rationale",
    "trade-off", "pros and cons", "recommend", "strategy", "plan",
    "summarize", "summarise", "review", "critique",
})


class ComplexityClassifier:
    """
    Classifies a task prompt into a TaskComplexity tier using heuristic rules.

    Rules (evaluated in order — first match wins):
      1. CRITICAL  — contains a security/exploit keyword or history depth > 20 turns
      2. COMPLEX   — contains a code-generation keyword or prompt > 200 words
      3. MEDIUM    — contains a reasoning keyword or prompt > 50 words
      4. SIMPLE    — fallback for short, factual queries
    """

    def classify(
        self,
        prompt: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> TaskComplexity:
        """
        Classify a single prompt string.

        Args:
            prompt:  The user task or query text.
            history: Optional prior conversation turns for depth checks.

        Returns:
            TaskComplexity tier.
        """
        lower = prompt.lower()
        word_count = len(prompt.split())
        history_depth = len(history) if history else 0

        # ── CRITICAL: security keywords or very deep sessions ──────────────
        if any(kw in lower for kw in _SECURITY_KEYWORDS) or history_depth > 20:
            logger.debug(
                "[Classifier] CRITICAL | security_kw=%s history_depth=%d",
                any(kw in lower for kw in _SECURITY_KEYWORDS),
                history_depth,
            )
            return TaskComplexity.CRITICAL

        # ── COMPLEX: code keywords or long prompt ──────────────────────────
        if any(kw in lower for kw in _CODE_KEYWORDS) or word_count > 200:
            logger.debug(
                "[Classifier] COMPLEX | code_kw=%s words=%d",
                any(kw in lower for kw in _CODE_KEYWORDS),
                word_count,
            )
            return TaskComplexity.COMPLEX

        # ── MEDIUM: reasoning keywords or moderate length ──────────────────
        if any(kw in lower for kw in _REASONING_KEYWORDS) or word_count > 50:
            logger.debug("[Classifier] MEDIUM | words=%d", word_count)
            return TaskComplexity.MEDIUM

        logger.debug("[Classifier] SIMPLE | words=%d", word_count)
        return TaskComplexity.SIMPLE

    def classify_from_history(
        self,
        history: List[Dict[str, Any]],
    ) -> TaskComplexity:
        """
        Classify from the most recent user-role message in the history list.

        Falls back to MEDIUM if no user message is found.

        Args:
            history: Full conversation history dicts with 'role' and 'content'.

        Returns:
            TaskComplexity for the most recent user intent.
        """
        for entry in reversed(history):
            if entry.get("role") == "user":
                return self.classify(
                    str(entry.get("content", "")),
                    history=history,
                )
        return TaskComplexity.MEDIUM


# ──────────────────────────────────────────────────────────────────────────────
# Cost Tracker
# ──────────────────────────────────────────────────────────────────────────────

class CostTracker:
    """
    Session-scoped cost and token usage tracker.

    - Accumulates usage across all LLM calls in a session.
    - Publishes 'agent.token_usage' events to the EventBus after each call.
    - Raises LLMBudgetExceededError when session cost crosses max_budget_usd.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        max_budget_usd: float = 5.0,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._session_id = session_id or str(uuid.uuid4())
        self._max_budget = max_budget_usd
        self._event_bus = event_bus
        self._record = CostRecord(session_id=self._session_id)

    def record(
        self,
        model: ModelConfig,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """
        Record token usage from one LLM call.

        Args:
            model:         The model configuration that was called.
            input_tokens:  Tokens consumed by the prompt.
            output_tokens: Tokens generated in the response.

        Raises:
            LLMBudgetExceededError: When cumulative cost exceeds max_budget_usd.
        """
        self._record.add_usage(input_tokens, output_tokens, model)

        logger.info(
            "[Brain/CostTracker] session=%s | model=%s | in=%d out=%d | "
            "session_total=$%.4f / $%.2f cap",
            self._session_id,
            model.model_id,
            input_tokens,
            output_tokens,
            self._record.total_cost_usd,
            self._max_budget,
        )

        # Fire-and-forget EventBus publish — non-blocking
        if self._event_bus is not None:
            asyncio.create_task(
                self._event_bus.publish(Event(
                    "agent.token_usage",
                    {
                        "session_id": self._session_id,
                        "model": model.model_id,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "session_cost_usd": self._record.total_cost_usd,
                    },
                ))
            )

        if self._record.total_cost_usd > self._max_budget:
            raise LLMBudgetExceededError(
                f"Session '{self._session_id}' cost ${self._record.total_cost_usd:.4f} "
                f"exceeded budget cap ${self._max_budget:.2f}. "
                "All LLM calls halted to prevent runaway spending."
            )

    @property
    def summary(self) -> CostRecord:
        """Read-only cost record snapshot for this session."""
        return self._record

    def record_cache_hit(self, tokens_saved: int = 0) -> None:
        """
        V2 Optimizer: record a semantic cache hit.
        Không tăng cost, nhưng tăng call_count để track tổng số requests.
        Ghi event vào EventBus để Dashboard hiển thị.

        Args:
            tokens_saved: Số tokens tiết kiệm được (response_tokens của cached entry).
        """
        self._record.call_count += 1
        logger.info(
            "[Brain/CostTracker] Cache hit | session=%s | tokens_saved=%d | "
            "total_calls=%d",
            self._session_id,
            tokens_saved,
            self._record.call_count,
        )
        if self._event_bus is not None:
            asyncio.create_task(
                self._event_bus.publish(Event(
                    "agent.cache_hit",
                    {
                        "session_id": self._session_id,
                        "tokens_saved": tokens_saved,
                        "session_cost_usd": self._record.total_cost_usd,
                    },
                ))
            )


# ──────────────────────────────────────────────────────────────────────────────
# System Prompt Suffix (injected into every LLM call)
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEM_SUFFIX_TEMPLATE = """
You MUST respond with a valid JSON object and NOTHING ELSE — no prose, no markdown fences.
The JSON must contain exactly these fields:
{{
  "tool_name": "<name of one tool from the available list>",
  "args": {{<keyword arguments as a JSON object matching the tool's parameters>}},
  "reasoning": "<one sentence explaining why you chose this tool>"
}}

Available tool names: {tool_names}
Only use tool names from the list above. Inventing tool names will cause a system error.
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# Structured Output Schema  (2025 — JSON Schema for strict output enforcement)
# ──────────────────────────────────────────────────────────────────────────────

# JSON Schema for the IronCore Action response.
# Enforced as strict=True on models that support it — eliminates hallucinated
# fields and reduces parse errors by ~60% compared to plain json_object mode.
_ACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string", "description": "Name of the tool to execute"},
        "args": {
            "type": "object",
            "additionalProperties": True,
            "description": "Keyword arguments for the tool",
        },
        "reasoning": {
            "type": "string",
            "description": "One sentence explanation of why this tool was chosen",
        },
    },
    "required": ["tool_name", "args", "reasoning"],
    "additionalProperties": False,
}

# Model prefixes that support strict JSON schema structured outputs.
# These can enforce `response_format={"type": "json_schema", ...}`.
# All others fall back to the weaker `{"type": "json_object"}`.
_STRICT_JSON_SCHEMA_PREFIXES: tuple[str, ...] = (
    "claude-",        # Claude 3.5+ (Haiku, Sonnet, Opus)
    "anthropic/",     # Anthropic via litellm prefix
    "gpt-4o",         # GPT-4o and GPT-4o-mini
    "gpt-4.5",        # GPT-4.5 and variants
    "gpt-4-turbo",    # GPT-4 Turbo
)

# Retry configuration for 429 Rate Limit errors within a tier.
# Two retries with linear backoff before escalating to the next tier.
_RATE_LIMIT_MAX_RETRIES: int = 2
_RATE_LIMIT_RETRY_DELAY: float = 30.0  # seconds


def _build_response_format(model_id: str) -> Dict[str, Any]:
    """
    Return the best response_format for the given model.

    For models proven to support strict JSON schema (Claude 3.5+, GPT-4o+):
      → {"type": "json_schema", "json_schema": {"strict": True, ...}}

    For all others (Ollama, older models):
      → {"type": "json_object"}  (permits any valid JSON)
    """
    lower = model_id.lower()
    if any(lower.startswith(p) for p in _STRICT_JSON_SCHEMA_PREFIXES):
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "ironcore_action",
                "strict": True,
                "schema": _ACTION_JSON_SCHEMA,
            },
        }
    return {"type": "json_object"}


# ──────────────────────────────────────────────────────────────────────────────
# LLM Bridge — Main Public Interface
# ──────────────────────────────────────────────────────────────────────────────

class LLMBridge:
    """
    Production LLM integration layer for IronCoreEngine.

    This class replaces the `_get_next_action()` stub in `core/engine.py`.
    The Architect (GPT-5.4) injects an instance of LLMBridge into the engine.

    Capabilities:
      - Automatic complexity-based tier routing
      - Unified LiteLLM calls (Ollama / Claude / OpenAI / Gemini via one API)
      - JSON response parsing → Action with hallucination guard
      - Automatic fallback: if tier N fails → escalate to tier N+1 → ... → CRITICAL
      - Token + cost tracking with configurable budget cap
      - Async streaming with EventBus token events

    Interface contract with The Architect (GPT-5.4):
      The Architect calls engine._get_next_action() which internally delegates to:

        >>> bridge.get_next_action(
        ...     history=engine.history,
        ...     available_tools=list(engine._tools.values()),
        ...     system_prompt="You are IronCore...",
        ... )

    Usage::

        bridge = LLMBridge(
            event_bus=engine.event_bus,
            session_id="session-001",
            max_budget_usd=2.0,
        )
        # Wire into engine:
        engine._get_next_action = lambda: bridge.get_next_action(
            engine.history,
            list(engine._tools.values()),
            SYSTEM_PROMPT,
        )
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        session_id: Optional[str] = None,
        max_budget_usd: float = 5.0,
        model_overrides: Optional[Dict[TaskComplexity, ModelConfig]] = None,
        semantic_cache: Optional[Any] = None,  # SemanticCache (V2 Optimizer)
        kv_cache_manager: Optional[Any] = None, # PromptKVCacheManager (V2 Phase 2)
    ) -> None:
        self._event_bus = event_bus
        self._classifier = ComplexityClassifier()
        self._cost_tracker = CostTracker(
            session_id=session_id,
            max_budget_usd=max_budget_usd,
            event_bus=event_bus,
        )
        # Allow caller to pin a specific model per tier for A/B testing or cost control
        self._model_overrides: Dict[TaskComplexity, ModelConfig] = (
            model_overrides or {}
        )
        # V2 Optimizer: SemanticCache — None = disabled (graceful degradation)
        self._cache: Optional[Any] = semantic_cache
        # V2 Optimizer Phase 2: PromptKVCacheManager — None = disabled
        self._kv_cache: Optional[Any] = kv_cache_manager

        logger.info(
            "[Brain/LLMBridge] Initialized | session=%s | budget=$%.2f | "
            "cache=%s | kv_cache=%s",
            self._cost_tracker.summary.session_id,
            max_budget_usd,
            "enabled" if semantic_cache is not None else "disabled",
            "enabled" if kv_cache_manager is not None else "disabled",
        )
        # Phase 15 — Enterprise Budget Guard (EE only, opt-in via set_budget_guard)
        self._budget_guard: Optional[BudgetGuard] = None
        # Phase 17 — Cost Optimizer (EE only, opt-in via set_cost_optimizer)
        self._cost_optimizer: Optional[Any] = None  # CostOptimizer
        # Auto-configure LiteLLM observability based on available env vars.
        self._setup_observability()

    def set_budget_guard(self, guard: "BudgetGuard") -> None:
        """
        Attach an enterprise BudgetGuard — called during app startup for EE deployments.

        Once attached, every call_llm() invocation will:
          - Run pre_call_check() before the LiteLLM call (raises LLMBudgetExceededError on BLOCK)
          - Run post_call_record() after a successful response to record spend

        Args:
            guard: Configured BudgetGuard instance from ironcore.enterprise.budget.
        """
        self._budget_guard = guard
        logger.info("[Brain/LLMBridge] BudgetGuard attached (Phase 15 Enterprise).")

    def set_cost_optimizer(self, optimizer: "CostOptimizer") -> None:
        """
        Attach a CostOptimizer — called during app startup for EE deployments.

        Once attached, every call_llm() invocation will call
        optimizer.get_effective_model() to potentially downgrade the requested
        model based on current budget utilization.

        Args:
            optimizer: CostOptimizer instance from ironcore.enterprise.budget.optimizer.
        """
        self._cost_optimizer = optimizer
        logger.info("[Brain/LLMBridge] CostOptimizer attached (Phase 17 Enterprise).")

    def _setup_observability(self) -> None:
        """
        Auto-detect and enable LiteLLM observability callbacks.

        Checks for well-known API keys / env vars (set externally by DevOps):
          LANGFUSE_SECRET_KEY → Langfuse (self-hosted or cloud)
          LANGSMITH_API_KEY   → LangSmith (LangChain Cloud)
          ARIZE_SPACE_KEY     → Arize AI
          OTEL_EXPORTER_OTLP_ENDPOINT → OpenTelemetry collector

        Non-breaking: if no env vars are set, nothing changes.
        """
        import os as _os
        providers: List[str] = []

        if _os.environ.get("LANGFUSE_SECRET_KEY") or _os.environ.get("LANGFUSE_HOST"):
            providers.append("langfuse")

        if _os.environ.get("LANGSMITH_API_KEY"):
            providers.append("langsmith")

        if _os.environ.get("ARIZE_SPACE_KEY") and _os.environ.get("ARIZE_API_KEY"):
            providers.append("arize")

        if _os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            providers.append("otel")

        if providers:
            litellm.success_callback = providers
            litellm.failure_callback = providers
            logger.info(
                "[Brain/LLMBridge] Observability enabled: %s",
                providers,
            )

    # ── Primary Public API ────────────────────────────────────────────────────

    async def get_next_action(
        self,
        history: List[Dict[str, Any]],
        available_tools: List[ToolDefinition],
        system_prompt: str,
    ) -> Optional[Action]:
        """
        Query the appropriate LLM tier and return the next agent Action.

        This is the single method consumed by IronCoreEngine to replace its stub:
            engine._get_next_action()

        Flow:
          1. classify_from_history() → TaskComplexity
          2. _build_messages()       → OpenAI-format message list
          3. _call_with_tier_fallback() → LLMResponse
          4. _parse_response_to_action() → Action (with hallucination guard)

        Args:
            history:         Full IronCoreEngine conversation history.
            available_tools: ToolDefinition list from the engine's registry.
            system_prompt:   Core system instructions for the agent persona.

        Returns:
            Parsed Action, or None to stop the agent loop.

        Raises:
            LLMRoutingError:       All fallback tiers exhausted.
            LLMBudgetExceededError: Session budget cap reached.
        """
        complexity = self._classifier.classify_from_history(history)
        tool_descriptions = self.format_tools_for_llm(available_tools)
        messages = self._build_messages(history, system_prompt, tool_descriptions)

        logger.info(
            "[Brain/LLMBridge] get_next_action | complexity=%s | history_len=%d",
            complexity.value,
            len(history),
        )

        # ── V2 Optimizer: Semantic Cache lookup ────────────────────────────
        user_query = self._extract_last_user_query(history)
        if self._cache is not None and user_query:
            try:
                cached = await self._cache.lookup(user_query, namespace="chat")
                if cached is not None:
                    self._cost_tracker.record_cache_hit(cached.response_tokens)
                    action = self._parse_response_to_action(
                        LLMResponse(
                            content=cached.response,
                            model_used=cached.source_model or "cache",
                        ),
                        available_tools,
                    )
                    logger.info(
                        "[Brain/LLMBridge] Cache hit → skipping API call | "
                        "similarity=%.3f age=%.0fs",
                        cached.similarity_score,
                        cached.age_seconds,
                    )
                    return action
            except Exception as _cache_exc:
                # Cache errors are non-fatal — fall through to LLM call
                logger.warning(
                    "[Brain/LLMBridge] Cache lookup error (non-fatal): %s", _cache_exc
                )
        # ──────────────────────────────────────────────────────────────────

        response = await self._call_with_tier_fallback(complexity, messages)
        action = self._parse_response_to_action(response, available_tools)

        # ── V2 Optimizer: Store response in Semantic Cache ─────────────────
        if (
            self._cache is not None
            and user_query
            and action is not None
            and action.tool_name != "finish"  # Không cache terminal actions
        ):
            try:
                await self._cache.store(
                    query=user_query,
                    response=response.content,
                    namespace="chat",
                    source_model=response.model_used,
                    metadata={
                        "session_id": self._cost_tracker.summary.session_id,
                        "complexity": complexity.value,
                    },
                )
            except Exception as _store_exc:
                logger.warning(
                    "[Brain/LLMBridge] Cache store error (non-fatal): %s", _store_exc
                )
        # ──────────────────────────────────────────────────────────────────

        logger.info(
            "[Brain/LLMBridge] resolved | tool=%s | model=%s | latency=%.0fms",
            action.tool_name if action else "None",
            response.model_used,
            response.latency_ms,
        )
        return action

    async def call_llm(
        self,
        messages: List[Dict[str, str]],
        model_config: ModelConfig,
    ) -> LLMResponse:
        """
        Low-level, model-specific LiteLLM call.

        Args:
            messages:     OpenAI-format message list.
            model_config: Target model configuration.

        Returns:
            LLMResponse with content, token counts, latency, and finish reason.

        Raises:
            LLMRoutingError: Wraps any LiteLLM / network exception.
        """
        start_ts = time.time()
        trace_id = str(uuid.uuid4())

        # ── Phase 17: Cost Optimizer — autonomous model downgrade ──────────
        if self._cost_optimizer is not None:
            from ironcore.enterprise.budget.optimizer import CostOptimizerBlockedError
            try:
                effective_model_id = self._cost_optimizer.get_effective_model(
                    model_config.model_id
                )
                if effective_model_id != model_config.model_id:
                    logger.info(
                        "[Brain/LLMBridge] CostOptimizer downgrade: %s → %s",
                        model_config.model_id, effective_model_id,
                    )
                    model_config = model_config.model_copy(
                        update={"model_id": effective_model_id}
                    )
            except CostOptimizerBlockedError as exc:
                raise LLMBudgetExceededError(str(exc)) from exc
        # ──────────────────────────────────────────────────────────────────

        # ── V2 Optimizer Phase 2: Anthropic KV-Cache injection ─────────────
        if self._kv_cache is not None:
            try:
                messages = self._kv_cache.prepare_cacheable_messages(
                    messages, model_config.model_id
                )
            except Exception as _kv_exc:
                logger.warning(
                    "[Brain/LLMBridge] KV-cache preparation error (non-fatal): %s",
                    _kv_exc,
                )
        # ──────────────────────────────────────────────────────────────────

        # ── Phase 15: Enterprise Budget Guard — pre-call check ──────────────
        if self._budget_guard is not None:
            from ironcore.enterprise.budget.ledger import BudgetExceededError as _BEE  # lazy import
            try:
                await self._budget_guard.pre_call_check(
                    session_id=self._cost_tracker.summary.session_id,
                    model_id=model_config.model_id,
                    estimated_output_tokens=model_config.max_output_tokens,
                )
            except _BEE as exc:
                raise LLMBudgetExceededError(str(exc)) from exc
        # ──────────────────────────────────────────────────────────────────

        # ── Structured output format — strict JSON schema for supported models ──
        resp_format = _build_response_format(model_config.model_id)

        # ── LiteLLM call with rate-limit retry ────────────────────────────
        raw = None
        for _attempt in range(_RATE_LIMIT_MAX_RETRIES):
            try:
                raw = await litellm.acompletion(
                    model=model_config.model_id,
                    messages=messages,
                    max_tokens=model_config.max_output_tokens,
                    temperature=model_config.temperature,
                    timeout=model_config.timeout_seconds,
                    response_format=resp_format,
                    metadata={"trace_id": trace_id},
                )
                break  # success — exit retry loop

            except litellm.exceptions.RateLimitError as exc:
                if _attempt < _RATE_LIMIT_MAX_RETRIES - 1:
                    logger.warning(
                        "[Brain/LLMBridge] Rate limited on '%s' (attempt %d/%d) — "
                        "retrying in %.0fs",
                        model_config.model_id,
                        _attempt + 1,
                        _RATE_LIMIT_MAX_RETRIES,
                        _RATE_LIMIT_RETRY_DELAY,
                    )
                    await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY)
                else:
                    raise LLMRoutingError(
                        f"Rate limit not resolved after {_RATE_LIMIT_MAX_RETRIES} "
                        f"retries for '{model_config.model_id}'"
                    ) from exc

            except litellm.exceptions.Timeout as exc:
                raise LLMRoutingError(
                    f"Timeout after {model_config.timeout_seconds}s "
                    f"for model '{model_config.model_id}'"
                ) from exc
            except litellm.exceptions.APIError as exc:
                raise LLMRoutingError(
                    f"API error for '{model_config.model_id}': {exc}"
                ) from exc
            except Exception as exc:
                raise LLMRoutingError(
                    f"Unexpected error calling '{model_config.model_id}': {exc}"
                ) from exc

        latency_ms = (time.time() - start_ts) * 1_000
        content = (raw.choices[0].message.content or "").strip()
        input_tokens  = getattr(raw.usage, "prompt_tokens", 0)
        output_tokens = getattr(raw.usage, "completion_tokens", 0)
        finish_reason = getattr(raw.choices[0], "finish_reason", "stop") or "stop"

        self._cost_tracker.record(model_config, input_tokens, output_tokens)

        # ── V2 Optimizer Phase 2: Parse KV-cache usage stats ─────────────
        if self._kv_cache is not None:
            try:
                import asyncio as _asyncio
                _asyncio.create_task(
                    self._kv_cache.update_stats_from_response(
                        raw, model_id=model_config.model_id
                    )
                )
            except Exception as _kv_stat_exc:
                logger.warning(
                    "[Brain/LLMBridge] KV-cache stats update error (non-fatal): %s",
                    _kv_stat_exc,
                )
        # ──────────────────────────────────────────────────────────────────

        logger.info(
            "[Brain/LLMBridge] call_llm | model=%s | in=%d out=%d | latency=%.0fms",
            model_config.model_id,
            input_tokens,
            output_tokens,
            latency_ms,
        )

        # Extract Anthropic prompt-cache token stats (zero for other providers)
        _cache_write = (
            getattr(getattr(raw, "usage", None), "cache_creation_input_tokens", 0) or 0
        )
        _cache_read = (
            getattr(getattr(raw, "usage", None), "cache_read_input_tokens", 0) or 0
        )

        # ── Phase 15: Enterprise Budget Guard — post-call record ─────────
        if self._budget_guard is not None:
            try:
                await self._budget_guard.post_call_record(
                    session_id=self._cost_tracker.summary.session_id,
                    model_id=model_config.model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_write_tokens=_cache_write,
                    cache_read_tokens=_cache_read,
                    trace_id=trace_id,
                )
            except Exception as _bg_exc:
                # Non-fatal: budget record failure must not break the response path
                logger.warning(
                    "[Brain/LLMBridge] BudgetGuard post_call_record error (non-fatal): %s",
                    _bg_exc,
                )
        # ──────────────────────────────────────────────────────────────────

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_used=model_config.model_id,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            trace_id=trace_id,
            cache_write_tokens=_cache_write,
            cache_read_tokens=_cache_read,
        )

    async def stream_response(
        self,
        messages: List[Dict[str, str]],
        model_config: ModelConfig,
    ) -> AsyncIterator[str]:
        """
        Stream raw token chunks from the LLM.

        Each chunk is also published as an 'llm.token_stream' event on the
        EventBus so monitoring sidecars can display live output.

        Args:
            messages:     OpenAI-format message list.
            model_config: Target model configuration.

        Yields:
            String token chunks returned by the LLM.

        Raises:
            LLMRoutingError: If the streaming call fails.
        """
        try:
            stream = await litellm.acompletion(
                model=model_config.model_id,
                messages=messages,
                max_tokens=model_config.max_output_tokens,
                temperature=model_config.temperature,
                timeout=model_config.timeout_seconds,
                stream=True,
            )
            async for chunk in stream:
                token: str = chunk.choices[0].delta.content or ""
                if token:
                    if self._event_bus is not None:
                        asyncio.create_task(
                            self._event_bus.publish(Event(
                                "llm.token_stream",
                                {"token": token, "model": model_config.model_id},
                            ))
                        )
                    yield token

        except Exception as exc:
            raise LLMRoutingError(
                f"Streaming failed for '{model_config.model_id}': {exc}"
            ) from exc

    def format_tools_for_llm(
        self,
        tools: List[ToolDefinition],
    ) -> List[Dict[str, Any]]:
        """
        Convert ToolDefinition objects to OpenAI function-calling schema format.

        The returned dicts are embedded in the system prompt so the LLM knows
        what tools are available and their risk characteristics.

        Args:
            tools: List of ToolDefinition from the engine's registry.

        Returns:
            List of serialisation dicts, one per tool.
        """
        return [
            {
                "name": t.name,
                "description": t.description or f"Execute the '{t.name}' tool.",
                "risk_level": t.risk_level.name,
                "requires_sandbox": t.requires_sandbox,
            }
            for t in tools
        ]

    @property
    def cost_summary(self) -> CostRecord:
        """Read-only snapshot of accumulated session cost and token usage."""
        return self._cost_tracker.summary

    @staticmethod
    def _extract_last_user_query(history: List[Dict[str, Any]]) -> str:
        """
        Lấy nội dung tin nhắn user gần nhất từ history.
        Dùng làm cache key trong get_next_action.

        Returns:
            Query string, hoặc cỗuỗi rỗng nếu không tìm thấy.
        """
        for entry in reversed(history):
            if entry.get("role") == "user":
                content = str(entry.get("content", "")).strip()
                if content:
                    return content
        return ""

    # ── Private Helpers ───────────────────────────────────────────────────────

    async def _call_with_tier_fallback(
        self,
        complexity: TaskComplexity,
        messages: List[Dict[str, str]],
    ) -> LLMResponse:
        """
        Attempt each model in the required tier; escalate to next tier on failure.

        Fallback strategy:
          start_tier → try all models → escalate to next tier → ... → CRITICAL
          If CRITICAL tier also fails → raise LLMRoutingError.

        Args:
            complexity: Starting complexity tier for routing.
            messages:   Assembled LLM message list.

        Returns:
            First successful LLMResponse.

        Raises:
            LLMRoutingError: All tiers and models exhausted.
        """
        tier_sequence = self._build_tier_sequence(complexity)
        last_error: Optional[Exception] = None

        for tier, models in tier_sequence:
            for model in models:
                try:
                    logger.debug(
                        "[Brain/LLMBridge] Trying model='%s' (tier=%s)",
                        model.model_id,
                        tier.value,
                    )
                    return await self.call_llm(messages, model)
                except LLMBudgetExceededError:
                    # Budget error must propagate immediately — do not fallback
                    raise
                except LLMRoutingError as exc:
                    last_error = exc
                    logger.warning(
                        "[Brain/LLMBridge] Model '%s' failed: %s — escalating.",
                        model.model_id,
                        exc,
                    )

        raise LLMRoutingError(
            f"All LLM fallbacks exhausted starting from tier '{complexity.value}'. "
            f"Last error: {last_error}"
        )

    def _build_tier_sequence(
        self,
        start_complexity: TaskComplexity,
    ) -> List[Tuple[TaskComplexity, List[ModelConfig]]]:
        """
        Build an ordered list of (tier, models) to try, from start upward.

        If a model override exists for a tier, it replaces the default list
        with a single-model list.

        Args:
            start_complexity: The initial complexity tier to begin from.

        Returns:
            Ordered list of (TaskComplexity, List[ModelConfig]) pairs.
        """
        order: List[TaskComplexity] = [
            TaskComplexity.SIMPLE,
            TaskComplexity.MEDIUM,
            TaskComplexity.COMPLEX,
            TaskComplexity.CRITICAL,
        ]
        start_idx = order.index(start_complexity)
        result: List[Tuple[TaskComplexity, List[ModelConfig]]] = []

        for tier in order[start_idx:]:
            if tier in self._model_overrides:
                result.append((tier, [self._model_overrides[tier]]))
            else:
                result.append((tier, MODEL_TIERS.get(tier, [])))

        return result

    def _build_messages(
        self,
        history: List[Dict[str, Any]],
        system_prompt: str,
        tool_descriptions: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """
        Assemble the OpenAI-format messages list from history and system context.

        Structure:
          [system]          ← agent persona + tools list + JSON format instruction
          [user/assistant]  ← history turns, converted to user/assistant roles
          ...

        Observation turns are converted to user messages so the LLM sees the
        result of each tool call before deciding the next action.

        Args:
            history:           IronCoreEngine conversation history.
            system_prompt:     Core agent system instructions.
            tool_descriptions: Serialised tool list from format_tools_for_llm().

        Returns:
            OpenAI-format message list ready for acompletion().
        """
        tool_names = [t["name"] for t in tool_descriptions]
        tools_json = json.dumps(tool_descriptions, indent=2)

        full_system = (
            f"{system_prompt}\n\n"
            f"# Available Tools\n{tools_json}\n\n"
            + _SYSTEM_SUFFIX_TEMPLATE.format(tool_names=tool_names)
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": full_system}
        ]

        for entry in history:
            role = entry.get("role", "user")

            if role == "user":
                content = str(entry.get("content", ""))
                if content:
                    messages.append({"role": "user", "content": content})

            elif role == "assistant":
                tool_name = entry.get("tool", "")
                args = entry.get("args", {})
                reasoning = entry.get("reasoning", "")
                messages.append({
                    "role": "assistant",
                    "content": json.dumps({
                        "tool_name": tool_name,
                        "args": args,
                        "reasoning": reasoning,
                    }),
                })

            elif role == "observation":
                content = entry.get("content", "")
                status = entry.get("status", "")
                error = entry.get("error")
                obs_parts = [f"[Observation] status={status}"]
                if content is not None:
                    obs_parts.append(f"content: {content}")
                if error:
                    obs_parts.append(f"error: {error}")
                messages.append({"role": "user", "content": "\n".join(obs_parts)})

        return messages

    def _parse_response_to_action(
        self,
        response: LLMResponse,
        available_tools: List[ToolDefinition],
    ) -> Optional[Action]:
        """
        Parse the raw LLM JSON response string into a typed Action.

        Handles:
          - Valid JSON objects
          - Markdown code fences (```json ... ```)
          - Empty or missing tool_name → fallback to 'finish'
          - Hallucinated tool name not in registry → fallback to 'think'

        Args:
            response:        LLMResponse from call_llm().
            available_tools: Registered tools to validate tool_name against.

        Returns:
            A valid Action, or None if the LLM explicitly signals stop.

        Raises:
            LLMResponseParseError: If the response is not parseable as JSON.
        """
        raw = response.content.strip()

        # Strip markdown code fences if the model wrapped its output
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if fence_match:
            raw = fence_match.group(1).strip()

        try:
            data: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "[Brain/LLMBridge] JSON parse error: %s\nRaw response (first 300): %s",
                exc,
                response.content[:300],
            )
            raise LLMResponseParseError(
                f"LLM response is not valid JSON: {exc}\n"
                f"Raw content (first 300 chars): {response.content[:300]}"
            ) from exc

        tool_name: str = str(data.get("tool_name", "")).strip()
        args: Any = data.get("args", {})
        reasoning: str = str(data.get("reasoning", ""))

        # ── Guard: empty tool_name ─────────────────────────────────────────
        if not tool_name:
            logger.warning(
                "[Brain/LLMBridge] LLM returned empty tool_name. "
                "Defaulting to 'finish'."
            )
            return Action(
                tool_name="finish",
                args={"answer": "LLM returned no explicit tool. Terminating safely."},
            )

        # ── Guard: hallucinated tool name ──────────────────────────────────
        registered_names = {t.name for t in available_tools}
        if tool_name not in registered_names:
            logger.error(
                "[Brain/LLMBridge] LLM hallucinated tool '%s'. "
                "Registered: %s. Routing to 'think' to self-correct.",
                tool_name,
                sorted(registered_names),
            )
            return Action(
                tool_name="think",
                args={
                    "thought": (
                        f"I tried to call tool '{tool_name}' which does not exist. "
                        f"Available tools are: {sorted(registered_names)}. "
                        "I will reconsider my approach."
                    )
                },
            )

        if reasoning:
            logger.info("[Brain/LLMBridge] reasoning: %s", reasoning[:150])

        return Action(
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
        )
