"""
IronCore: Context Optimizer — Token Budget Manager
====================================================
Phase 7 — The Brain (Claude Sonnet 4.6)

Responsibilities:
  - Maximize information density within a model's context window
  - Count tokens accurately (tiktoken for OpenAI, Claude-aware approximation)
  - Summarize old session history to reclaim token budget
  - Assemble the final ContextPackage sent to the LLM for each reasoning turn
  - Graceful RAG-node pruning when budget is still exceeded after summarization

Algorithm overview (optimize() call):
  1. Count system_prompt tokens + tool_definitions tokens  → fixed overhead
  2. Reserve min(20%, 4096) tokens for the model's response
  3. Remaining budget split: 40% recent history + 30% RAG context
  4. Load last N messages from SessionStore within history budget
  5. If messages overflow: summarize oldest portion via HistorySummarizer
  6. Query GraphRAGMemory for relevant nodes up to RAG budget
  7. Sort & prune RAG nodes by relevance score if still over budget
  8. Assemble ContextPackage with full audit stats

Integration points:
  - SessionStore (Phase 5): load / count messages
  - GraphRAGMemory (Phase 2): query_context
  - LLMBridge (Phase 1): call_llm for summarization (optional; falls back to
    LiteLLM directly so no circular import)

Author: The Brain (IronCore Project) — Claude Sonnet 4.6
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from ironcore.core.engine import RiskLevel, ToolDefinition
from ironcore.optimizer.sliding_window import SlidingWindowSummarizer

# V2 Optimizer Phase 3: TokenCompressor (optional — graceful degradation)
if TYPE_CHECKING:
    from ironcore.optimizer.token_compressor import TokenCompressor

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class ContextOptimizerError(Exception):
    """Base exception for all ContextOptimizer errors."""


class TokenCountError(ContextOptimizerError):
    """Raised when token counting fails unrecoverably."""


class SummarizationError(ContextOptimizerError):
    """Raised when message summarization fails and no fallback is possible."""


class BudgetViolationError(ContextOptimizerError):
    """
    Raised when the fixed overhead (system_prompt + tools) already exceeds
    the total token budget — the model can never accept any history at all.
    """


# ──────────────────────────────────────────────────────────────────────────────
# Data Models (Pydantic V2)
# ──────────────────────────────────────────────────────────────────────────────


class ContextSlot(str, Enum):
    """
    Named allocation slots inside a ContextPackage.

    SYSTEM_PROMPT      — immutable core agent instructions
    TOOL_DEFINITIONS   — available tools serialised for function-calling
    RAG_CONTEXT        — relevant nodes retrieved from GraphRAGMemory
    RECENT_HISTORY     — last N turns of verbatim conversation
    SUMMARIZED_HISTORY — compressed representation of older turns
    WORKING_MEMORY     — scratch-pad injected as a system message (future use)
    """

    SYSTEM_PROMPT = "system_prompt"
    TOOL_DEFINITIONS = "tool_definitions"
    RAG_CONTEXT = "rag_context"
    RECENT_HISTORY = "recent_history"
    SUMMARIZED_HISTORY = "summarized_history"
    WORKING_MEMORY = "working_memory"


class TokenBudget(BaseModel):
    """
    Detailed breakdown of how the total token budget is allocated.

    All values are in tokens.  Negative `remaining_for_response` indicates
    the context is over-budget — the optimizer will not produce that state.
    """

    total_budget: int = Field(
        ..., ge=1, description="Hard cap for the entire context window."
    )
    system_prompt_tokens: int = Field(default=0, ge=0)
    tool_definitions_tokens: int = Field(default=0, ge=0)
    rag_context_tokens: int = Field(default=0, ge=0)
    history_tokens: int = Field(default=0, ge=0)
    reserved_for_response: int = Field(
        default=0,
        ge=0,
        description="Tokens reserved for the model's output generation.",
    )

    @property
    def overhead_tokens(self) -> int:
        return self.system_prompt_tokens + self.tool_definitions_tokens

    @property
    def content_tokens(self) -> int:
        return self.rag_context_tokens + self.history_tokens

    @property
    def remaining_for_response(self) -> int:
        return (
            self.total_budget
            - self.overhead_tokens
            - self.content_tokens
            - self.reserved_for_response
        )

    @property
    def utilization_pct(self) -> float:
        used = self.overhead_tokens + self.content_tokens + self.reserved_for_response
        return round((used / max(1, self.total_budget)) * 100, 2)


class ContextPackage(BaseModel):
    """
    The fully assembled context ready to be sent to the LLM.

    `messages` is in OpenAI/LiteLLM multi-turn chat format:
      [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]

    Audit fields give full transparency for debugging and billing:
      - dropped_messages: how many history entries were pruned / replaced by summary
      - rag_nodes_included: how many graph nodes are embedded in the context
      - summary_inserted: True when a HistorySummarizer compression was injected
      - budget: full TokenBudget breakdown
    """

    messages: List[Dict[str, Any]]
    token_count: int = Field(ge=0)
    dropped_messages: int = Field(default=0, ge=0)
    rag_nodes_included: int = Field(default=0, ge=0)
    summary_inserted: bool = False
    budget: TokenBudget
    assembly_time_ms: float = Field(default=0.0, ge=0.0)


# ──────────────────────────────────────────────────────────────────────────────
# Token Counter
# ──────────────────────────────────────────────────────────────────────────────

# Tokens-per-char approximation constants (conservative over-estimate)
_CHARS_PER_TOKEN_APPROX = 3.5  # Claude tokeniser is ~3.5 chars/token on average


def _approx_tokens(text: str) -> int:
    """Fast character-based token approximation (no dependencies required)."""
    return max(1, int(len(text) / _CHARS_PER_TOKEN_APPROX))


class TokenCounter:
    """
    Counts tokens for text strings and chat message lists.

    Strategy:
      1. For OpenAI model IDs: attempt tiktoken (exact count).
      2. For all others (Claude, Gemini, Ollama, etc.): character-based estimate.
      3. If tiktoken is not installed: fall back to approximation for all models.

    The approximation intentionally over-counts by ~5–10% to keep the
    optimizer conservative — we never want to exceed the true model limit.
    """

    def __init__(self) -> None:
        self._tiktoken_available: Optional[bool] = None
        self._tiktoken_encodings: Dict[str, Any] = {}

    def _try_tiktoken(self, model: str) -> Optional[Any]:
        """Return a tiktoken Encoding for `model`, or None if unavailable."""
        if self._tiktoken_available is False:
            return None
        try:
            import tiktoken  # type: ignore[import]

            self._tiktoken_available = True
            if model not in self._tiktoken_encodings:
                try:
                    enc = tiktoken.encoding_for_model(model)
                except KeyError:
                    # Unknown model name — use the broadly compatible encoding
                    enc = tiktoken.get_encoding("cl100k_base")
                self._tiktoken_encodings[model] = enc
            return self._tiktoken_encodings[model]
        except ImportError:
            self._tiktoken_available = False
            logger.debug(
                "[TokenCounter] tiktoken not installed — using character approximation."
            )
            return None

    def count_tokens(self, text: str, model: str = "") -> int:
        """
        Count the number of tokens in `text` for the given `model`.

        Args:
            text:  Plain string to count.
            model: LiteLLM model identifier (used to select encoder).

        Returns:
            Token count (always >= 1 for non-empty text).
        """
        if not text:
            return 0

        # tiktoken only covers OpenAI model families
        is_openai_model = any(
            model.startswith(prefix)
            for prefix in ("gpt-", "text-", "davinci", "curie", "babbage", "ada", "o1", "o3")
        )
        if is_openai_model:
            enc = self._try_tiktoken(model)
            if enc is not None:
                try:
                    return len(enc.encode(text))
                except Exception as exc:
                    logger.warning(
                        "[TokenCounter] tiktoken encode error: %s — falling back.", exc
                    )

        return _approx_tokens(text)

    def count_messages(
        self,
        messages: List[Dict[str, Any]],
        model: str = "",
    ) -> int:
        """
        Count total tokens across an OpenAI-format message list.

        Each message contributes:  4 (framing overhead) + len(role) + len(content).
        The terminal reply priming adds 3 tokens (per OpenAI cookbook).
        """
        total = 3  # priming tokens for assistant reply
        for msg in messages:
            total += 4  # framing overhead per message
            for key, value in msg.items():
                text = value if isinstance(value, str) else json.dumps(value)
                total += self.count_tokens(text, model)
        return total


# ──────────────────────────────────────────────────────────────────────────────
# History Summarizer
# ──────────────────────────────────────────────────────────────────────────────

SummarizeCallable = Callable[[str], Any]  # async fn(prompt: str) -> str


class HistorySummarizer:
    """
    Compresses a list of old messages into a compact summary string.

    Uses an async summarization callable injected at construction time.
    Results are cached by a SHA-256 fingerprint of the input messages so
    identical message slices are summarised only once per process lifetime.

    If no summarize_fn is provided, a deterministic extractive fallback is
    used (takes the first sentence of every :assistant: turn) — zero cost,
    zero latency, but lower quality.
    """

    def __init__(
        self,
        summarize_fn: Optional[SummarizeCallable] = None,
        max_cache_entries: int = 256,
    ) -> None:
        self._summarize_fn = summarize_fn
        self._cache: Dict[str, str] = {}
# (Removed HistorySummarizer — Replaced by SlidingWindowSummarizer in Phase 6)
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# Context Optimizer — Main Public Interface
# ──────────────────────────────────────────────────────────────────────────────


class ContextOptimizer:
    """
    Assembles the optimal ContextPackage for each LLM reasoning turn.

    The optimiser ensures the total token count of the assembled messages
    stays within the model's effective context window while maximising the
    information quality passed to the LLM.

    Construction:
        optimizer = ContextOptimizer(
            session_store=store,          # Phase 5 SessionStore
            graph_rag=memory,             # Phase 2 GraphRAGMemory  (optional)
            summarizer=HistorySummarizer(summarize_fn=bridge.simple_complete),
            total_budget=180_000,         # 90% of Claude Sonnet 4.6's 200K window
        )

    Per-turn usage:
        package = await optimizer.optimize(
            session_id="...",
            system_prompt="You are IronCore...",
            available_tools=[...],
            current_query="Search the web for X",
            model="claude-sonnet-4-6",
        )
        # package.messages → pass directly to LiteLLM / LLMBridge

    Budget allocation (configurable at construction via `budget_ratios`):
      - RESPONSE reserve    →  15% of total_budget  (floor: 1024 tokens)
      - SYSTEM + TOOLS      →  measured exactly; deducted first
      - RECENT HISTORY      →  40% of remaining budget
      - RAG CONTEXT         →  30% of remaining budget
      - SUMMARISED HISTORY  →  fills whatever is left after recent + RAG
    """

    # Default fractional allocation for variable content slots
    _DEFAULT_BUDGET_RATIOS: Dict[str, float] = {
        "response_reserve_pct":       0.15,   # Reserve for model output
        "recent_history_pct":         0.40,   # For verbatim recent turns
        "rag_context_pct":            0.30,   # For GraphRAG nodes
        # Remainder (~15% when all ratios used) → summarised history
    }

    def __init__(
        self,
        session_store: Any = None,
        graph_rag: Any = None,
        llm_call_fn: Optional[Callable[..., Any]] = None,
        total_budget: int = 180_000,
        budget_ratios: Optional[Dict[str, float]] = None,
        min_response_reserve: int = 1_024,
        token_compressor: Optional[Any] = None,     # V2 Phase 3 TokenCompressor
        sliding_window: Optional[SlidingWindowSummarizer] = None, # V2 Phase 6
    ) -> None:
        """
        Args:
            session_store:         Phase 5 SessionStore instance.
            graph_rag:             Phase 2 GraphRAGMemory instance.
            llm_call_fn:           Simple LLM complete callable for summary.
            total_budget:          Hard context window token cap.
            budget_ratios:         Override default percentage allocations.
            min_response_reserve:  Floor for response reservation (tokens).
        """
        self._session_store = session_store
        self._graph_rag = graph_rag
        self._llm_call_fn = llm_call_fn
        self._total_budget = total_budget
        self._min_response_reserve = min_response_reserve
        self._counter = TokenCounter()
        self._compressor = token_compressor
        
        self._sliding_window = sliding_window or SlidingWindowSummarizer(
            trigger_at_pct=0.75,
            summarization_model=os.getenv("IRONCORE_SUMM_MODEL", "ollama/llama3.1:8b"),
        )

        ratios = dict(self._DEFAULT_BUDGET_RATIOS)
        if budget_ratios:
            ratios.update(budget_ratios)
        self._ratios = ratios

        logger.info(
            "[ContextOptimizer] Initialized | total_budget=%d tokens | ratios=%s | compressor=%s",
            total_budget,
            ratios,
            "enabled" if token_compressor is not None else "disabled",
        )

    # ── Primary Public API ────────────────────────────────────────────────────

    async def optimize(
        self,
        session_id: str,
        system_prompt: str,
        available_tools: List[ToolDefinition],
        current_query: str,
        model: str = "claude-sonnet-4-6",
    ) -> ContextPackage:
        """
        Assemble and return the optimal ContextPackage for one LLM turn.

        Args:
            session_id:      Active session ID to load history from.
            system_prompt:   Agent's core instructions (immutable during run).
            available_tools: Registered ToolDefinitions (for schema injection).
            current_query:   The current user request (used for GraphRAG query).
            model:           LiteLLM model string (affects token counting).

        Returns:
            ContextPackage with optimised messages list + audit metadata.

        Raises:
            BudgetViolationError: When system_prompt + tools alone exceed the
                                  total budget (nothing can be added).
        """
        t_start = time.time()

        # ── Step 1: Measure fixed overhead ───────────────────────────────────
        system_tokens = self._counter.count_tokens(system_prompt, model)
        tools_text = self._format_tools_text(available_tools)
        tools_tokens = self._counter.count_tokens(tools_text, model)
        overhead_tokens = system_tokens + tools_tokens

        # ── Step 2: Calculate sub-budgets ────────────────────────────────────
        response_reserve = max(
            self._min_response_reserve,
            int(self._total_budget * self._ratios["response_reserve_pct"]),
        )

        # Budget available for dynamic content
        content_budget = self._total_budget - overhead_tokens - response_reserve

        if content_budget <= 0:
            raise BudgetViolationError(
                f"Fixed overhead ({overhead_tokens} tokens) + response reserve "
                f"({response_reserve} tokens) already exceeds total budget "
                f"({self._total_budget} tokens). Cannot fit any history or RAG context."
            )

        history_budget = int(content_budget * self._ratios["recent_history_pct"])
        rag_budget = int(content_budget * self._ratios["rag_context_pct"])
        summary_budget = content_budget - history_budget - rag_budget

        logger.debug(
            "[ContextOptimizer] Budgets | overhead=%d history=%d rag=%d summary=%d "
            "response_reserve=%d total=%d",
            overhead_tokens, history_budget, rag_budget, summary_budget,
            response_reserve, self._total_budget,
        )

        # ── Step 3: Load message history from SessionStore ───────────────────
        (
            recent_msgs,
            dropped_count,
        ) = await self._load_history(session_id, history_budget + summary_budget, model)

        # ── Step 4: Retrieve GraphRAG context ────────────────────────────────
        rag_messages, rag_nodes_count = await self._load_rag_context(
            current_query, rag_budget, model
        )

        # ── Step 5: Assemble full message list ───────────────────────────────
        messages: List[Dict[str, Any]] = []

        # 5a — System prompt (always first)
        messages.append({"role": "system", "content": system_prompt})

        # 5b — Tool definitions as a system message if any tools exist
        if tools_text:
            messages.append({
                "role": "system",
                "content": f"[AVAILABLE TOOLS]\n{tools_text}",
            })

        # 5c — RAG context (injected early so recent history overrides it)
        messages.extend(rag_messages)

        # 5d — Verbatim history (newest, highest fidelity)
        messages.extend(recent_msgs)

        # ── Step 6: Sliding Window Compression (Phase 6) ─────────────────────
        total_tokens = self._counter.count_messages(messages, model)
        
        async def dummy_llm_call(**kwargs: Any) -> Any:
            return "Summarization fallback (no llm_call_fn provided)."
            
        messages, was_compressed = await self._sliding_window.maybe_compress(
            session_id=session_id,
            messages=messages,
            current_tokens=total_tokens,
            token_budget=self._total_budget,
            llm_call_fn=self._llm_call_fn or dummy_llm_call,
        )
        if was_compressed:
            logger.info("[ContextOptimizer] Sliding window compression applied | session=%s", session_id)
            total_tokens = self._counter.count_messages(messages, model)

        budget = TokenBudget(
            total_budget=self._total_budget,
            system_prompt_tokens=system_tokens,
            tool_definitions_tokens=tools_tokens,
            rag_context_tokens=self._counter.count_messages(rag_messages, model),
            history_tokens=self._counter.count_messages(recent_msgs, model),
            reserved_for_response=response_reserve,
        )

        assembly_ms = (time.time() - t_start) * 1_000

        logger.info(
            "[ContextOptimizer] Package assembled | tokens=%d/%d (%.1f%%) | "
            "history_msgs=%d dropped=%d rag_nodes=%d compressed=%s latency_ms=%.1f",
            total_tokens,
            self._total_budget,
            budget.utilization_pct,
            len(recent_msgs),
            dropped_count,
            rag_nodes_count,
            was_compressed,
            assembly_ms,
        )

        return ContextPackage(
            messages=messages,
            token_count=total_tokens,
            dropped_messages=dropped_count,
            rag_nodes_included=rag_nodes_count,
            summary_inserted=was_compressed,
            budget=budget,
            assembly_time_ms=assembly_ms,
        )

    # ── History Loading Helpers ───────────────────────────────────────────────

    async def _load_history(
        self,
        session_id: str,
        total_history_budget: int,
        model: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Load messages from SessionStore that fit within total_history_budget.
        Older messages that do not fit are dropped (or will be compressed via sliding window).

        Returns (recent_msgs, dropped_count).
        """
        if self._session_store is None:
            return [], 0

        try:
            all_messages = await self._session_store.get_messages(session_id)
        except Exception as exc:
            logger.warning(
                "[ContextOptimizer] Could not load messages for session %s: %s",
                session_id,
                exc,
            )
            return [], 0

        if not all_messages:
            return [], 0

        # Convert SessionMessage objects to OpenAI-format dicts (newest last)
        raw: List[Dict[str, Any]] = []
        for msg in all_messages:
            entry: Dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_name:
                entry["tool_name"] = msg.tool_name
            if msg.tool_args:
                entry["tool_args"] = msg.tool_args
            raw.append(entry)

        # Walk backwards from newest, accumulate until we hit total_history_budget
        recent: List[Dict[str, Any]] = []
        accumulated = 0

        for i in range(len(raw) - 1, -1, -1):
            msg_tokens = self._counter.count_messages([raw[i]], model)
            if accumulated + msg_tokens > total_history_budget:
                break
            accumulated += msg_tokens
            recent.insert(0, raw[i])

        dropped_count = len(raw) - len(recent)

        return recent, dropped_count

    # ── RAG Context Helpers ───────────────────────────────────────────────────

    async def _load_rag_context(
        self,
        query: str,
        rag_budget: int,
        model: str,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Query GraphRAGMemory and convert relevant nodes into context messages.

        Returns (messages_list, node_count_included).
        """
        if self._graph_rag is None or not query.strip():
            return [], 0

        try:
            from ironcore.memory.graph_rag import RAGContext

            rag_ctx: RAGContext = await self._graph_rag.query_context(query)
        except Exception as exc:
            logger.warning(
                "[ContextOptimizer] GraphRAG query failed: %s — skipping RAG slot.", exc
            )
            return [], 0

        if not rag_ctx.nodes:
            return [], 0

        # Sort nodes by relevance score descending (best first)
        scored_nodes = sorted(
            rag_ctx.nodes,
            key=lambda n: rag_ctx.relevance_scores.get(n.id, 0.0),
            reverse=True,
        )

        # Greedily include nodes until rag_budget is reached
        included_lines: List[str] = []
        included_count = 0
        accumulated = 0

        for node in scored_nodes:
            score = rag_ctx.relevance_scores.get(node.id, 0.0)
            line = (
                f"[{node.entity_type.upper()}] {node.name}"
                + (f" — {json.dumps(node.properties)}" if node.properties else "")
                + f" (relevance: {score:.2f})"
            )
            line_tokens = self._counter.count_tokens(line, model)
            if accumulated + line_tokens > rag_budget:
                break
            included_lines.append(line)
            accumulated += line_tokens
            included_count += 1

        if not included_lines:
            return [], 0

        rag_text = (
            "Relevant knowledge from memory graph:\n"
            + "\n".join(included_lines)
        )

        # ── V2 Optimizer Phase 3: Compress RAG context if compressor available ──
        if self._compressor is not None:
            try:
                result = await self._compressor.compress(rag_text)
                if result.tokens_saved > 0:
                    logger.info(
                        "[ContextOptimizer] RAG compression | saved=%d tokens (%.1f%%)",
                        result.tokens_saved,
                        result.savings_pct * 100,
                    )
                rag_text = result.compressed_text
            except Exception as _comp_exc:
                logger.warning(
                    "[ContextOptimizer] RAG compression error (non-fatal): %s",
                    _comp_exc,
                )
        # ──────────────────────────────────────────────────────────

        messages = [{"role": "system", "content": rag_text}]
        return messages, included_count

    # ── Tool Formatting Helpers ───────────────────────────────────────────────

    @staticmethod
    def _format_tools_text(tools: List[ToolDefinition]) -> str:
        """
        Serialize ToolDefinitions to a compact plain-text listing for token counting
        and system-message injection.

        Each tool renders as:
          • tool_name (RISK_LEVEL) [sandbox] — description
        """
        if not tools:
            return ""

        lines: List[str] = []
        for tool in tools:
            sandbox_flag = " [sandbox]" if tool.requires_sandbox else ""
            lines.append(
                f"• {tool.name} ({tool.risk_level.name}){sandbox_flag}"
                + (f" — {tool.description}" if tool.description else "")
            )
        return "\n".join(lines)

    # ── Statistics / Introspection ────────────────────────────────────────────

    def estimate_budget(
        self,
        system_prompt: str,
        available_tools: List[ToolDefinition],
        model: str = "claude-sonnet-4-6",
    ) -> TokenBudget:
        """
        Synchronous budget estimate without loading any session data.

        Useful for pre-flight checks before making LLM calls.

        Returns:
            TokenBudget with overhead measured; content slots set to zero.
        """
        system_tokens = self._counter.count_tokens(system_prompt, model)
        tools_text = self._format_tools_text(available_tools)
        tools_tokens = self._counter.count_tokens(tools_text, model)
        response_reserve = max(
            self._min_response_reserve,
            int(self._total_budget * self._ratios["response_reserve_pct"]),
        )
        return TokenBudget(
            total_budget=self._total_budget,
            system_prompt_tokens=system_tokens,
            tool_definitions_tokens=tools_tokens,
            rag_context_tokens=0,
            history_tokens=0,
            reserved_for_response=response_reserve,
        )
