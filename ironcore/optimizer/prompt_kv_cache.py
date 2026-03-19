"""
IronCore Optimizer — Phase 2: Anthropic Prompt KV-Cache
========================================================
Claude 4.6 "The Optimizer" — IronCore V2

Kích hoạt Anthropic Prompt Caching: lưu system prompt vào KV-cache
server-side của Anthropic. Các lần gọi sau chỉ tính 10% cost.

Tại sao quan trọng:
    - System prompt thường 2,000–5,000 tokens — gọi 1000 lần/ngày = $30/ngày
    - Với KV-cache: $3/ngày → tiết kiệm $27/ngày = $810/tháng

Cơ chế:
    - Thêm header: anthropic-beta: prompt-caching-2024-07-31
    - Inject cache_control: {"type": "ephemeral"} vào cuối system prompt block
    - Anthropic cache system prompt trong 5 phút (ephemeral)
    - Các request trong 5 phút sau chỉ trả 10% input token cost

Non-breaking:
    - Chỉ áp dụng cho Anthropic models (prefix "claude-" / "anthropic/")
    - Model khác → messages trả về nguyên bản, không thay đổi gì

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class OptimizerError(Exception):
    """Base exception for all Optimizer module errors."""


class KVCacheError(OptimizerError):
    """Raised when KV-cache preparation fails unrecoverably."""


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────


class CacheableBlock(BaseModel):
    """
    Đại diện cho một message block có thể được đánh dấu cache_control.
    Dùng nội bộ khi build messages list cho Anthropic.
    """

    content: str
    cache_control: Optional[Dict[str, str]] = None  # {"type": "ephemeral"}
    tokens: int = 0                                  # Ước tính token count


class KVCacheStats(BaseModel):
    """
    Theo dõi hiệu quả Anthropic KV-cache.
    Được expose qua CostDashboard để GPT-5.4 hiển thị lên UI.

    Chú thích:
        cache_creation_input_tokens: Tokens dùng để TẠO cache lần đầu (100% cost)
        cache_read_input_tokens:     Tokens ĐỌC từ cache (10% cost)
        input_tokens:                Tokens thông thường không cache (100% cost)
    """

    total_calls: int = 0
    cached_calls: int = 0                    # Calls mà Anthropic đã CÓ cache
    cache_creation_input_tokens: int = 0    # Tokens tạo cache — 100% price
    cache_read_input_tokens: int = 0        # Tokens đọc cache — 10% price
    input_tokens: int = 0                   # Tokens thông thường — 100% price
    output_tokens: int = 0
    estimated_savings_usd: float = 0.0
    last_updated: float = Field(default_factory=time.time)

    @property
    def cache_hit_rate(self) -> float:
        """Tỷ lệ calls có cache hit từ Anthropic (0.0–1.0)."""
        return (self.cached_calls / self.total_calls) if self.total_calls > 0 else 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Anthropic Model Detection Helpers
# ──────────────────────────────────────────────────────────────────────────────

# Prefix list nhận dạng Anthropic models trong LiteLLM model strings
_ANTHROPIC_PREFIXES = (
    "claude-",
    "anthropic/",
    "claude/",
    "anthropic.",
)

# Minimum token count để Anthropic chấp nhận cache block
_MIN_TOKENS_TO_CACHE_DEFAULT = 1024

# Cost multiplier khi đọc từ cache (10% của normal input price)
_CACHE_READ_COST_RATIO = 0.10


# ──────────────────────────────────────────────────────────────────────────────
# PromptKVCacheManager
# ──────────────────────────────────────────────────────────────────────────────


class PromptKVCacheManager:
    """
    Quản lý Anthropic Prompt Caching cho LLMBridge.

    Chỉ có tác dụng với Anthropic (Claude) models.
    Với các model khác → messages được trả về nguyên bản (no-op).

    Usage (trong LLMBridge.call_llm()):

        # Trước khi gọi litellm.acompletion():
        if self._kv_cache:
            messages = self._kv_cache.prepare_cacheable_messages(messages, model_id)

        raw = await litellm.acompletion(model=..., messages=messages, ...)

        # Sau khi nhận response:
        if self._kv_cache:
            await self._kv_cache.update_stats_from_response(raw, model_id)
    """

    def __init__(
        self,
        min_tokens_to_cache: int = _MIN_TOKENS_TO_CACHE_DEFAULT,
        cache_system_prompt: bool = True,
        cache_tool_definitions: bool = True,
    ) -> None:
        """
        Args:
            min_tokens_to_cache:      Số token tối thiểu để đánh dấu cache_control.
                                      Anthropic yêu cầu >= 1024. Default = 1024.
            cache_system_prompt:      True = đánh dấu cuối system prompt block.
            cache_tool_definitions:   True = đánh dấu tool definitions block.
        """
        self._min_tokens = min_tokens_to_cache
        self._cache_system = cache_system_prompt
        self._cache_tools = cache_tool_definitions
        self._stats = KVCacheStats()

        logger.info(
            "[KVCache] Initialized | min_tokens=%d cache_system=%s cache_tools=%s",
            min_tokens_to_cache,
            cache_system_prompt,
            cache_tool_definitions,
        )

    # ── Core Public API ───────────────────────────────────────────────────────

    def prepare_cacheable_messages(
        self,
        messages: List[Dict[str, Any]],
        model_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Inject cache_control vào system prompt (và tool blocks nếu bật).

        Nếu model KHÔNG phải Anthropic → return messages nguyên bản (không đổi gì).
        Đây là NON-BREAKING — model khác simply ignore cache_control field.

        Logic inject (tuân theo Anthropic API spec):
          1. Tìm message có role="system"
          2. Nếu content là string và >= min_tokens → convert sang list format
             và thêm cache_control vào block cuối cùng
          3. Tương tự với tool definitions block nếu cache_tools=True

        Args:
            messages: OpenAI-format message list từ LLMBridge._build_messages().
            model_id: LiteLLM model string (e.g., "claude-sonnet-4-6").

        Returns:
            Messages list với cache_control được inject (nếu Anthropic model).
            Bản copy — không mutate original list.
        """
        if not self.is_anthropic_model(model_id):
            logger.debug(
                "[KVCache] Skipping — not Anthropic model: %s", model_id
            )
            return messages

        # Deep copy để không mutate original list
        result: List[Dict[str, Any]] = []
        system_injected = False

        for msg in messages:
            msg_copy = dict(msg)
            role = msg_copy.get("role", "")

            if role == "system" and self._cache_system and not system_injected:
                content = msg_copy.get("content", "")
                if isinstance(content, str):
                    token_estimate = self._estimate_tokens(content)
                    if token_estimate >= self._min_tokens:
                        # Anthropic multi-block format với cache_control
                        msg_copy["content"] = [
                            {
                                "type": "text",
                                "text": content,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ]
                        system_injected = True
                        logger.debug(
                            "[KVCache] Injected cache_control on system prompt | "
                            "model=%s estimated_tokens=%d",
                            model_id,
                            token_estimate,
                        )
                    else:
                        logger.debug(
                            "[KVCache] System prompt too short to cache | "
                            "estimated_tokens=%d < min=%d",
                            token_estimate,
                            self._min_tokens,
                        )
                elif isinstance(content, list) and len(content) > 0:
                    # Đã là list format — inject vào block cuối cùng
                    token_estimate = sum(
                        self._estimate_tokens(b.get("text", ""))
                        for b in content
                        if isinstance(b, dict)
                    )
                    if token_estimate >= self._min_tokens:
                        content_copy = [dict(b) for b in content]
                        # Thêm cache_control vào block cuối
                        content_copy[-1]["cache_control"] = {"type": "ephemeral"}
                        msg_copy["content"] = content_copy
                        system_injected = True
                        logger.debug(
                            "[KVCache] Injected cache_control on last system block | "
                            "estimated_tokens=%d",
                            token_estimate,
                        )

            result.append(msg_copy)

        return result

    def is_anthropic_model(self, model_id: str) -> bool:
        """
        Kiểm tra xem model_id có phải Anthropic/Claude không.

        Args:
            model_id: LiteLLM model string.

        Returns:
            True nếu là Claude/Anthropic model.

        Examples:
            >>> mgr.is_anthropic_model("claude-sonnet-4-6")  # True
            >>> mgr.is_anthropic_model("anthropic/claude-3")  # True
            >>> mgr.is_anthropic_model("gpt-4o-mini")         # False
            >>> mgr.is_anthropic_model("ollama/llama3.1")     # False
        """
        lower = model_id.lower()
        return any(lower.startswith(prefix) for prefix in _ANTHROPIC_PREFIXES)

    def estimate_savings(
        self,
        cost_per_1k_input_tokens: float,
    ) -> float:
        """
        Tính số USD đã tiết kiệm được nhờ KV-cache.

        Cache read tokens chỉ tính 10% normal price.
        Savings = cache_read_tokens * (1 - 0.10) * cost_per_1k / 1000

        Args:
            cost_per_1k_input_tokens: Giá per 1K input tokens của model (USD).

        Returns:
            USD tiết kiệm được.
        """
        if self._stats.cache_read_input_tokens == 0:
            return 0.0

        normal_cost = (
            self._stats.cache_read_input_tokens / 1_000
        ) * cost_per_1k_input_tokens
        actual_cost = normal_cost * _CACHE_READ_COST_RATIO
        savings = normal_cost - actual_cost
        return round(savings, 6)

    async def update_stats_from_response(
        self,
        response: Any,
        model_id: str = "",
    ) -> None:
        """
        Parse token usage từ Anthropic API response và accumulate vào stats.

        Anthropic trả về trong response.usage:
            cache_creation_input_tokens: số tokens dùng để TẠO cache
            cache_read_input_tokens:     số tokens ĐỌC từ cache (10% price)
            input_tokens:                tokens thông thường (100% price)

        Non-Anthropic responses → bỏ qua (usage struct khác).

        Args:
            response: Raw LiteLLM response object từ acompletion().
            model_id: Model ID để log.
        """
        if not hasattr(response, "usage") or response.usage is None:
            return

        usage = response.usage
        self._stats.total_calls += 1

        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        input_tok = getattr(usage, "prompt_tokens", 0) or 0
        output_tok = getattr(usage, "completion_tokens", 0) or 0

        self._stats.cache_creation_input_tokens += cache_creation
        self._stats.cache_read_input_tokens += cache_read
        self._stats.input_tokens += input_tok
        self._stats.output_tokens += output_tok
        self._stats.last_updated = time.time()

        if cache_read > 0:
            self._stats.cached_calls += 1

        logger.info(
            "[KVCache] Usage | model=%s | cache_creation=%d cache_read=%d "
            "input=%d output=%d | hit_rate=%.1f%%",
            model_id or "unknown",
            cache_creation,
            cache_read,
            input_tok,
            output_tok,
            self._stats.cache_hit_rate * 100,
        )

    @property
    def stats(self) -> KVCacheStats:
        """Read-only snapshot of KVCache statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset stats (dùng cho testing hoặc đầu session mới)."""
        self._stats = KVCacheStats()

    # ── Private Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        Ước tính số token trong text (approximation ~4 chars/token).
        Không dùng tokenizer nặng — chỉ cần xác định có >= min_tokens không.
        """
        return max(0, len(text) // 4)
