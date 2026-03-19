"""
IronCore V2 — Phase 2 Tests: Anthropic Prompt KV-Cache
=======================================================
Tests cho ironcore/optimizer/prompt_kv_cache.py

Chạy: python -m pytest tests/test_phase2_optimizer_kvcache.py -v

Test coverage:
  - prepare_cacheable_messages với Claude → có cache_control block
  - prepare_cacheable_messages với GPT → KHÔNG có cache_control (unchanged)
  - prepare_cacheable_messages với Ollama → KHÔNG thay đổi
  - System prompt < 1024 tokens → không inject cache_control
  - System prompt >= 1024 tokens → inject đúng format
  - Already list-format system prompt → inject vào block cuối
  - update_stats_from_response với Anthropic usage fields
  - update_stats_from_response với response không có cache fields
  - estimate_savings tính chính xác
  - is_anthropic_model nhận dạng đúng các prefix

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from ironcore.optimizer.prompt_kv_cache import (
    KVCacheStats,
    PromptKVCacheManager,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_manager(**kwargs) -> PromptKVCacheManager:
    """Tạo PromptKVCacheManager với config mặc định."""
    return PromptKVCacheManager(
        min_tokens_to_cache=kwargs.get("min_tokens_to_cache", 1024),
        cache_system_prompt=kwargs.get("cache_system_prompt", True),
        cache_tool_definitions=kwargs.get("cache_tool_definitions", True),
    )


def _make_messages(system_content: str, user_content: str = "Hello") -> List[Dict]:
    """Tạo messages list chuẩn OpenAI format."""
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _long_system_prompt(length: int = 5000) -> str:
    """Tạo system prompt đủ dài để vượt threshold."""
    # ~4 chars/token → 5000 chars ≈ 1250 tokens > 1024
    return "You are IronCore AI Agent. " * (length // 27 + 1)


def _short_system_prompt() -> str:
    """Tạo system prompt ngắn hơn 1024 tokens."""
    # ~200 chars ≈ 50 tokens < 1024
    return "You are a helpful assistant."


def _make_mock_response(
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    input_tokens: int = 100,
    output_tokens: int = 200,
) -> Any:
    """Tạo mock LiteLLM response với Anthropic cache usage fields."""
    mock = MagicMock()
    mock.usage.cache_creation_input_tokens = cache_creation_tokens
    mock.usage.cache_read_input_tokens = cache_read_tokens
    mock.usage.prompt_tokens = input_tokens
    mock.usage.completion_tokens = output_tokens
    return mock


# ──────────────────────────────────────────────────────────────────────────────
# Test: is_anthropic_model
# ──────────────────────────────────────────────────────────────────────────────


def test_is_anthropic_model_claude_prefix():
    """Nhận dạng đúng Claude models (claude- prefix)."""
    mgr = _make_manager()
    assert mgr.is_anthropic_model("claude-sonnet-4-6") is True
    assert mgr.is_anthropic_model("claude-haiku-3-5") is True
    assert mgr.is_anthropic_model("claude-opus-4-6") is True
    assert mgr.is_anthropic_model("claude-3-5-sonnet-20241022") is True


def test_is_anthropic_model_anthropic_prefix():
    """Nhận dạng đúng anthropic/ và anthropic. prefixes."""
    mgr = _make_manager()
    assert mgr.is_anthropic_model("anthropic/claude-3") is True
    assert mgr.is_anthropic_model("anthropic.claude-v2") is True


def test_is_anthropic_model_non_anthropic():
    """Non-Anthropic models phải trả về False."""
    mgr = _make_manager()
    assert mgr.is_anthropic_model("gpt-4o-mini") is False
    assert mgr.is_anthropic_model("gpt-4.5") is False
    assert mgr.is_anthropic_model("ollama/llama3.1") is False
    assert mgr.is_anthropic_model("gemini-2.0-flash") is False
    assert mgr.is_anthropic_model("deepseek/deepseek-r1") is False


# ──────────────────────────────────────────────────────────────────────────────
# Test: prepare_cacheable_messages với Claude (inject cache_control)
# ──────────────────────────────────────────────────────────────────────────────


def test_prepare_claude_long_prompt_has_cache_control():
    """
    Claude model + system prompt >= 1024 tokens
    → system message phải có cache_control: {"type": "ephemeral"}.
    """
    mgr = _make_manager(min_tokens_to_cache=1024)
    messages = _make_messages(_long_system_prompt(5000))

    result = mgr.prepare_cacheable_messages(messages, "claude-sonnet-4-6")

    system_msg = result[0]
    assert system_msg["role"] == "system"
    # Content phải là list format (Anthropic multi-block)
    assert isinstance(system_msg["content"], list)
    assert len(system_msg["content"]) == 1
    block = system_msg["content"][0]
    assert block["type"] == "text"
    assert "cache_control" in block
    assert block["cache_control"] == {"type": "ephemeral"}


def test_prepare_claude_does_not_mutate_original():
    """
    prepare_cacheable_messages phải trả về bản copy — không mutate original.
    """
    mgr = _make_manager()
    original_msgs = _make_messages(_long_system_prompt())
    original_system_content = original_msgs[0]["content"]

    _ = mgr.prepare_cacheable_messages(original_msgs, "claude-sonnet-4-6")

    # Original phải không thay đổi
    assert original_msgs[0]["content"] == original_system_content


def test_prepare_claude_user_message_unchanged():
    """
    Chỉ system message được inject — user messages phải nguyên bản.
    """
    mgr = _make_manager()
    messages = _make_messages(_long_system_prompt(), "user question here")

    result = mgr.prepare_cacheable_messages(messages, "claude-haiku-3-5")

    user_msg = result[1]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "user question here"


# ──────────────────────────────────────────────────────────────────────────────
# Test: prepare_cacheable_messages với GPT → UNCHANGED
# ──────────────────────────────────────────────────────────────────────────────


def test_prepare_gpt_returns_unchanged():
    """
    GPT model → messages trả về nguyên bản, không có cache_control.
    """
    mgr = _make_manager()
    messages = _make_messages(_long_system_prompt())

    result = mgr.prepare_cacheable_messages(messages, "gpt-4o-mini")

    # Phải giống hệt messages gốc
    assert result == messages
    # System content vẫn là string, không phải list
    assert isinstance(result[0]["content"], str)


def test_prepare_ollama_returns_unchanged():
    """
    Ollama model → messages trả về nguyên bản, không inject gì.
    """
    mgr = _make_manager()
    messages = _make_messages(_long_system_prompt())

    result = mgr.prepare_cacheable_messages(messages, "ollama/llama3.1")

    assert result == messages
    assert isinstance(result[0]["content"], str)


# ──────────────────────────────────────────────────────────────────────────────
# Test: System prompt < 1024 tokens → không inject cache_control
# ──────────────────────────────────────────────────────────────────────────────


def test_prepare_short_system_prompt_no_inject():
    """
    System prompt ngắn (< 1024 tokens) → KHÔNG inject cache_control.
    Content vẫn là string.
    """
    mgr = _make_manager(min_tokens_to_cache=1024)
    messages = _make_messages(_short_system_prompt())

    result = mgr.prepare_cacheable_messages(messages, "claude-sonnet-4-6")

    system_msg = result[0]
    # Content vẫn là string vì quá ngắn
    assert isinstance(system_msg["content"], str)
    # Không có cache_control
    assert "cache_control" not in system_msg


# ──────────────────────────────────────────────────────────────────────────────
# Test: Already list-format system content → inject vào block cuối
# ──────────────────────────────────────────────────────────────────────────────


def test_prepare_list_format_system_injects_last_block():
    """
    System message đã là list format → inject cache_control vào block cuối.
    """
    mgr = _make_manager(min_tokens_to_cache=10)  # threshold thấp để test dễ
    long_text = "A" * 200  # 200 chars ≈ 50 tokens, vượt threshold=10

    messages = [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": long_text},
                {"type": "text", "text": long_text + " block2"},
            ],
        },
        {"role": "user", "content": "hi"},
    ]

    result = mgr.prepare_cacheable_messages(messages, "claude-sonnet-4-6")

    sys_content = result[0]["content"]
    assert isinstance(sys_content, list)
    assert len(sys_content) == 2
    # Block cuối phải có cache_control
    assert "cache_control" in sys_content[-1]
    assert sys_content[-1]["cache_control"] == {"type": "ephemeral"}
    # Block đầu KHÔNG có cache_control
    assert "cache_control" not in sys_content[0]


# ──────────────────────────────────────────────────────────────────────────────
# Test: update_stats_from_response
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_stats_accumulates_correctly():
    """
    update_stats_from_response accumulate đúng tất cả fields.
    """
    mgr = _make_manager()
    response = _make_mock_response(
        cache_creation_tokens=2000,
        cache_read_tokens=1800,
        input_tokens=200,
        output_tokens=500,
    )

    await mgr.update_stats_from_response(response, "claude-sonnet-4-6")

    stats = mgr.stats
    assert stats.total_calls == 1
    assert stats.cached_calls == 1          # cache_read > 0
    assert stats.cache_creation_input_tokens == 2000
    assert stats.cache_read_input_tokens == 1800
    assert stats.input_tokens == 200
    assert stats.output_tokens == 500


@pytest.mark.asyncio
async def test_update_stats_no_cache_read_cached_calls_zero():
    """
    Response không có cache_read → cached_calls không tăng.
    """
    mgr = _make_manager()
    response = _make_mock_response(
        cache_creation_tokens=3000,
        cache_read_tokens=0,        # Lần gọi đầu tiên → tạo cache, chưa đọc
        input_tokens=300,
        output_tokens=400,
    )

    await mgr.update_stats_from_response(response, "claude-haiku-3-5")

    stats = mgr.stats
    assert stats.cached_calls == 0          # Chưa có lần đọc nào
    assert stats.cache_creation_input_tokens == 3000
    assert stats.cache_hit_rate == 0.0


@pytest.mark.asyncio
async def test_update_stats_multiple_calls_accumulate():
    """
    Gọi update_stats nhiều lần → accumulate đúng.
    """
    mgr = _make_manager()

    # Call 1: tạo cache
    await mgr.update_stats_from_response(
        _make_mock_response(cache_creation_tokens=2000, cache_read_tokens=0,
                            input_tokens=100, output_tokens=200),
        "claude-sonnet-4-6",
    )
    # Call 2: đọc cache
    await mgr.update_stats_from_response(
        _make_mock_response(cache_creation_tokens=0, cache_read_tokens=2000,
                            input_tokens=50, output_tokens=200),
        "claude-sonnet-4-6",
    )

    stats = mgr.stats
    assert stats.total_calls == 2
    assert stats.cached_calls == 1                    # Chỉ call 2 có cache read
    assert stats.cache_creation_input_tokens == 2000
    assert stats.cache_read_input_tokens == 2000
    assert stats.input_tokens == 150
    assert stats.cache_hit_rate == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_update_stats_response_without_usage():
    """
    Response không có usage attribute → không crash, stats không đổi.
    """
    mgr = _make_manager()
    mock_response = MagicMock(spec=[])  # Không có attribute "usage"

    await mgr.update_stats_from_response(mock_response, "claude-sonnet-4-6")

    stats = mgr.stats
    assert stats.total_calls == 0  # Không tăng


# ──────────────────────────────────────────────────────────────────────────────
# Test: estimate_savings
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_estimate_savings_correct_calculation():
    """
    estimate_savings tính đúng:
    savings = cache_read_tokens * (1 - 0.10) * cost_per_1k / 1000
    """
    mgr = _make_manager()

    # Giả lập 10,000 cache_read_input_tokens
    await mgr.update_stats_from_response(
        _make_mock_response(cache_creation_tokens=0, cache_read_tokens=10_000,
                            input_tokens=0, output_tokens=0),
        "claude-sonnet-4-6",
    )

    # Claude Sonnet 4.6: $3/M input tokens = $0.003/1k
    cost_per_1k = 0.003
    savings = mgr.estimate_savings(cost_per_1k)

    # 10000 tokens * $0.003/1k = $0.03 normal cost
    # Actual = $0.03 * 0.10 = $0.003
    # Savings = $0.03 - $0.003 = $0.027
    assert savings == pytest.approx(0.027, abs=0.0001)


def test_estimate_savings_zero_when_no_cache_hits():
    """Không có cache read → savings = 0."""
    mgr = _make_manager()
    savings = mgr.estimate_savings(cost_per_1k_input_tokens=0.003)
    assert savings == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Test: Integration — prepare → LLMBridge (kiểm tra không break non-Anthropic)
# ──────────────────────────────────────────────────────────────────────────────


def test_cache_disabled_config():
    """
    cache_system_prompt=False → system prompt không bị inject dù là Claude.
    """
    mgr = _make_manager(cache_system_prompt=False, min_tokens_to_cache=10)
    messages = _make_messages("Short system prompt that exceeds our low threshold x" * 5)

    result = mgr.prepare_cacheable_messages(messages, "claude-sonnet-4-6")

    # Vì cache_system=False → content vẫn là string
    assert isinstance(result[0]["content"], str)


def test_reset_stats_clears_all():
    """reset_stats() phải xóa sạch tất cả counters."""
    mgr = _make_manager()
    mgr._stats.total_calls = 10
    mgr._stats.cached_calls = 5
    mgr._stats.cache_read_input_tokens = 50_000

    mgr.reset_stats()

    assert mgr.stats.total_calls == 0
    assert mgr.stats.cached_calls == 0
    assert mgr.stats.cache_read_input_tokens == 0
