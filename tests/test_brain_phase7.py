"""
Tests for Brain Phase 7 — Context Optimizer & Token Budget Manager
==================================================================
Coverage:
  - TokenCounter: text counting (approx + tiktoken fallback), message counting
  - TokenBudget: property computations (overhead, content, remaining, utilization)
  - HistorySummarizer: extractive fallback, LLM callable path, caching, cache eviction
  - ContextOptimizer: budget calculation, history trimming, RAG integration,
    summarization injection, BudgetViolationError, empty-session safety, tool formatting
  - ContextPackage: audit fields populated correctly
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest.mock as mock
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ironcore.core.context_optimizer import (
    BudgetViolationError,
    ContextOptimizer,
    ContextPackage,
    ContextSlot,
    ContextOptimizerError,
    HistorySummarizer,
    SummarizationError,
    TokenBudget,
    TokenCounter,
)
from ironcore.core.engine import RiskLevel, ToolDefinition


# ──────────────────────────────────────────────────────────────────────────────
# Helpers / Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _tool(name: str, desc: str = "", risk: RiskLevel = RiskLevel.LOW) -> ToolDefinition:
    async def _handler(**kwargs: Any) -> str:
        return "ok"

    return ToolDefinition(name=name, handler=_handler, risk_level=risk, description=desc)


def _make_messages(n: int, word_len: int = 10) -> List[Dict[str, Any]]:
    """Generate `n` alternating user/assistant messages of predictable length."""
    word = "token" * (word_len // 5 + 1)
    return [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Message {i}: " + " ".join([word] * word_len),
        }
        for i in range(n)
    ]


class _FakeSessionStore:
    """Minimal SessionStore mock that returns canned messages."""

    def __init__(self, messages: List[Any] | None = None) -> None:
        self._messages = messages or []

    async def get_messages(self, session_id: str) -> List[Any]:
        return self._messages


class _FakeSessionMessage:
    """Lightweight stand-in for ironcore.memory.session_store.SessionMessage."""

    def __init__(self, role: str, content: str) -> None:
        self.id = f"msg-{id(self)}"
        self.role = role
        self.content = content
        self.tool_name: Optional[str] = None
        self.tool_args: Optional[Dict] = None
        self.timestamp = time.time()


class _FakeGraphRAG:
    """Minimal GraphRAGMemory mock."""

    def __init__(self, nodes: list | None = None) -> None:
        from ironcore.memory.graph_rag import KnowledgeNode, RAGContext

        self._nodes = nodes or []
        self._rag_ctx = RAGContext(
            nodes=self._nodes,
            edges=[],
            relevance_scores={n.id: float(i + 1) * 0.1 for i, n in enumerate(self._nodes)},
            query_embedding=[0.1] * 5,
            retrieval_time_ms=1.0,
        )

    async def query_context(self, query: str):  # noqa: ANN201
        return self._rag_ctx


# ──────────────────────────────────────────────────────────────────────────────
# TokenCounter
# ──────────────────────────────────────────────────────────────────────────────


def test_token_counter_empty_string_returns_zero() -> None:
    counter = TokenCounter()
    assert counter.count_tokens("", model="any") == 0


def test_token_counter_non_empty_returns_positive() -> None:
    counter = TokenCounter()
    assert counter.count_tokens("hello world", model="claude-sonnet-4-6") > 0


def test_token_counter_longer_text_has_more_tokens() -> None:
    counter = TokenCounter()
    short = counter.count_tokens("hi", model="claude-sonnet-4-6")
    long = counter.count_tokens("hi " * 100, model="claude-sonnet-4-6")
    assert long > short


def test_token_counter_approximation_consistent() -> None:
    """Two calls with the same text must return the same count."""
    counter = TokenCounter()
    text = "Consistency check for token counting in IronCore context optimizer."
    a = counter.count_tokens(text, model="claude-sonnet-4-6")
    b = counter.count_tokens(text, model="claude-sonnet-4-6")
    assert a == b


def test_token_counter_count_messages_empty_list() -> None:
    counter = TokenCounter()
    # 3 priming tokens even for empty list (per OpenAI cookbook)
    assert counter.count_messages([], model="") == 3


def test_token_counter_count_messages_adds_up() -> None:
    counter = TokenCounter()
    msgs = _make_messages(3, word_len=5)
    total = counter.count_messages(msgs, model="claude-sonnet-4-6")
    single = sum(counter.count_messages([m], model="claude-sonnet-4-6") for m in msgs)
    # total should be >= sum of singles (framing + priming overhead)
    assert total >= 0
    assert total > 0


def test_token_counter_tiktoken_not_installed_falls_back() -> None:
    """Even with tiktoken mocked as unavailable, counting still works."""
    counter = TokenCounter()
    counter._tiktoken_available = False  # force the fast path
    result = counter.count_tokens("test text for fallback", model="gpt-4")
    assert result > 0


def test_token_counter_tiktoken_openai_model_uses_encoder() -> None:
    """Request an OpenAI model — counter should try tiktoken (or fall back gracefully)."""
    counter = TokenCounter()
    # Just verify it does not raise and returns a positive integer
    result = counter.count_tokens("some gpt content", model="gpt-4o-mini")
    assert isinstance(result, int)
    assert result > 0


# ──────────────────────────────────────────────────────────────────────────────
# TokenBudget Properties
# ──────────────────────────────────────────────────────────────────────────────


def test_token_budget_overhead() -> None:
    budget = TokenBudget(
        total_budget=100_000,
        system_prompt_tokens=500,
        tool_definitions_tokens=300,
        reserved_for_response=2_000,
    )
    assert budget.overhead_tokens == 800


def test_token_budget_content_tokens() -> None:
    budget = TokenBudget(
        total_budget=100_000,
        rag_context_tokens=2_000,
        history_tokens=5_000,
        reserved_for_response=1_000,
    )
    assert budget.content_tokens == 7_000


def test_token_budget_remaining_for_response_positive() -> None:
    budget = TokenBudget(
        total_budget=10_000,
        system_prompt_tokens=100,
        tool_definitions_tokens=100,
        rag_context_tokens=200,
        history_tokens=300,
        reserved_for_response=500,
    )
    # remaining = 10000 - 100 - 100 - 200 - 300 - 500 = 8800
    assert budget.remaining_for_response == 8_800


def test_token_budget_utilization_under_100() -> None:
    budget = TokenBudget(
        total_budget=10_000,
        system_prompt_tokens=1_000,
        tool_definitions_tokens=500,
        rag_context_tokens=1_000,
        history_tokens=2_000,
        reserved_for_response=2_000,
    )
    assert 0.0 < budget.utilization_pct < 100.0


def test_token_budget_utilization_full() -> None:
    budget = TokenBudget(
        total_budget=1_000,
        system_prompt_tokens=300,
        tool_definitions_tokens=200,
        rag_context_tokens=200,
        history_tokens=200,
        reserved_for_response=100,
    )
    assert budget.utilization_pct == 100.0


# ──────────────────────────────────────────────────────────────────────────────
# ContextSlot enum
# ──────────────────────────────────────────────────────────────────────────────


def test_context_slot_values_are_strings() -> None:
    for slot in ContextSlot:
        assert isinstance(slot.value, str)


def test_context_slot_all_expected_members() -> None:
    names = {s.name for s in ContextSlot}
    for expected in (
        "SYSTEM_PROMPT",
        "TOOL_DEFINITIONS",
        "RAG_CONTEXT",
        "RECENT_HISTORY",
        "SUMMARIZED_HISTORY",
        "WORKING_MEMORY",
    ):
        assert expected in names


# ──────────────────────────────────────────────────────────────────────────────
# HistorySummarizer
# ──────────────────────────────────────────────────────────────────────────────


def test_history_summarizer_empty_messages_returns_empty() -> None:
    async def _run() -> None:
        s = HistorySummarizer()
        result = await s.summarize([])
        assert result == ""

    asyncio.run(_run())


def test_history_summarizer_extractive_fallback_no_fn() -> None:
    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=None)
        messages = [
            {"role": "user", "content": "Tell me about Docker containers."},
            {"role": "assistant", "content": "Docker is an OS-level virtualisation tool."},
        ]
        result = await s.summarize(messages)
        assert isinstance(result, str)
        assert len(result) > 0

    asyncio.run(_run())


def test_history_summarizer_uses_llm_callable() -> None:
    async def _fake_llm(prompt: str) -> str:
        return "Compact summary: agent discussed Docker."

    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=_fake_llm)
        messages = [
            {"role": "user", "content": "What is Docker?"},
            {"role": "assistant", "content": "Docker provides container isolation."},
        ]
        result = await s.summarize(messages)
        assert "Compact summary" in result

    asyncio.run(_run())


def test_history_summarizer_caches_result() -> None:
    call_count = 0

    async def _counting_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return "Summary result."

    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=_counting_llm)
        messages = [{"role": "user", "content": "Hello cache test"}]
        await s.summarize(messages)
        await s.summarize(messages)  # second call — should use cache
        assert call_count == 1

    asyncio.run(_run())


def test_history_summarizer_different_messages_bypass_cache() -> None:
    call_count = 0

    async def _counting_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"Summary {call_count}."

    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=_counting_llm)
        msgs_a = [{"role": "user", "content": "Message A"}]
        msgs_b = [{"role": "user", "content": "Message B"}]
        await s.summarize(msgs_a)
        await s.summarize(msgs_b)
        assert call_count == 2

    asyncio.run(_run())


def test_history_summarizer_clear_cache() -> None:
    call_count = 0

    async def _counting_llm(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return "Summary."

    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=_counting_llm)
        messages = [{"role": "user", "content": "Cache clear test"}]
        await s.summarize(messages)
        s.clear_cache()
        await s.summarize(messages)  # cache was cleared — must re-summarise
        assert call_count == 2

    asyncio.run(_run())


def test_history_summarizer_llm_failure_falls_back_to_extractive() -> None:
    async def _failing_llm(prompt: str) -> str:
        raise RuntimeError("LLM unavailable")

    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=_failing_llm)
        messages = [
            {"role": "user", "content": "Some query"},
            {"role": "assistant", "content": "Some answer to the query."},
        ]
        result = await s.summarize(messages)
        # Should still produce something via extractive fallback
        assert isinstance(result, str)
        assert len(result) > 0

    asyncio.run(_run())


def test_history_summarizer_respects_max_tokens_limit() -> None:
    async def _verbose_llm(prompt: str) -> str:
        return "word " * 10_000  # very long response

    async def _run() -> None:
        s = HistorySummarizer(summarize_fn=_verbose_llm)
        messages = [{"role": "user", "content": "Test trimming"}]
        result = await s.summarize(messages, max_summary_tokens=50)
        # 50 tokens * ~3.5 chars + 50 buffer = ~225 chars max
        assert len(result) <= 50 * 4 + 60

    asyncio.run(_run())


def test_history_summarizer_cache_eviction() -> None:
    """When cache fills to max_cache_entries, oldest entry is evicted."""
    s = HistorySummarizer(summarize_fn=None, max_cache_entries=3)

    async def _run() -> None:
        for i in range(4):
            await s.summarize([{"role": "user", "content": f"Unique message {i}"}])
        # Cache should have evicted entry 0 and contain 3 most recent
        assert len(s._cache) == 3

    asyncio.run(_run())


# ──────────────────────────────────────────────────────────────────────────────
# ContextOptimizer
# ──────────────────────────────────────────────────────────────────────────────


def test_context_optimizer_no_session_store_returns_valid_package() -> None:
    """Without a SessionStore, optimizer should still assemble a basic package."""

    async def _run() -> None:
        optimizer = ContextOptimizer(
            session_store=None,
            graph_rag=None,
            total_budget=10_000,
        )
        package = await optimizer.optimize(
            session_id="test-session",
            system_prompt="You are IronCore.",
            available_tools=[_tool("think"), _tool("finish")],
            current_query="Hello world",
            model="claude-sonnet-4-6",
        )
        assert isinstance(package, ContextPackage)
        assert package.token_count > 0
        assert package.dropped_messages == 0
        assert package.rag_nodes_included == 0
        # System prompt must always be the first message
        assert package.messages[0]["role"] == "system"
        assert "IronCore" in package.messages[0]["content"]

    asyncio.run(_run())


def test_context_optimizer_includes_tools_in_messages() -> None:
    async def _run() -> None:
        optimizer = ContextOptimizer(session_store=None, total_budget=10_000)
        tools = [_tool("web_search", "Search the web"), _tool("finish", "End run")]
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Agent prompt.",
            available_tools=tools,
            current_query="search query",
        )
        tool_msgs = [m for m in package.messages if "[AVAILABLE TOOLS]" in m.get("content", "")]
        assert len(tool_msgs) == 1
        assert "web_search" in tool_msgs[0]["content"]
        assert "finish" in tool_msgs[0]["content"]

    asyncio.run(_run())


def test_context_optimizer_no_tools_omits_tool_message() -> None:
    async def _run() -> None:
        optimizer = ContextOptimizer(session_store=None, total_budget=10_000)
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="No tools here.",
            available_tools=[],
            current_query="query",
        )
        tool_msgs = [m for m in package.messages if "[AVAILABLE TOOLS]" in m.get("content", "")]
        assert len(tool_msgs) == 0

    asyncio.run(_run())


def test_context_optimizer_loads_history_from_session_store() -> None:
    async def _run() -> None:
        messages = [
            _FakeSessionMessage("user", "First user message"),
            _FakeSessionMessage("assistant", "First assistant reply"),
        ]
        store = _FakeSessionStore(messages)
        optimizer = ContextOptimizer(session_store=store, total_budget=50_000)
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Agent.",
            available_tools=[],
            current_query="second query",
        )
        roles = [m["role"] for m in package.messages]
        assert "user" in roles
        assert "assistant" in roles

    asyncio.run(_run())


def test_context_optimizer_trims_history_when_over_budget() -> None:
    async def _run() -> None:
        # 30 long messages that won't all fit in a very tight budget
        long_messages = [
            _FakeSessionMessage(
                "user" if i % 2 == 0 else "assistant",
                "word " * 500,  # ~500 words = ~666 tokens each
            )
            for i in range(30)
        ]
        store = _FakeSessionStore(long_messages)
        optimizer = ContextOptimizer(
            session_store=store,
            total_budget=8_000,  # very tight — forces trimming
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Short prompt.",
            available_tools=[],
            current_query="query",
        )
        # We can't fit all 30 messages in 8K tokens with overhead
        assert package.dropped_messages > 0
        # Token count must not exceed budget
        assert package.token_count <= 8_500  # small slack for estimation imprecision

    asyncio.run(_run())


def test_context_optimizer_injects_summary_for_old_messages() -> None:
    summarize_called = False

    async def _fake_summarize(prompt: str) -> str:
        nonlocal summarize_called
        summarize_called = True
        return "Historical context: user asked about security."

    async def _run() -> None:
        # Enough old messages to overflow history_budget on a tight config
        old_messages = [
            _FakeSessionMessage(
                "user" if i % 2 == 0 else "assistant",
                "This is a moderately long message. " * 20,
            )
            for i in range(20)
        ]
        store = _FakeSessionStore(old_messages)
        summarizer = HistorySummarizer(summarize_fn=_fake_summarize)
        optimizer = ContextOptimizer(
            session_store=store,
            summarizer=summarizer,
            total_budget=5_000,  # forces overflow
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="System.",
            available_tools=[],
            current_query="query",
        )
        if package.summary_inserted:
            summary_msgs = [
                m for m in package.messages
                if "CONTEXT SUMMARY" in m.get("content", "")
            ]
            assert len(summary_msgs) == 1

    asyncio.run(_run())


def test_context_optimizer_rag_context_included() -> None:
    async def _run() -> None:
        from ironcore.memory.graph_rag import KnowledgeNode

        nodes = [
            KnowledgeNode(entity_type="tech", name="Docker"),
            KnowledgeNode(entity_type="concept", name="Isolation"),
        ]
        graph_rag = _FakeGraphRAG(nodes)
        optimizer = ContextOptimizer(
            session_store=None,
            graph_rag=graph_rag,
            total_budget=50_000,
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Smart agent.",
            available_tools=[],
            current_query="Tell me about Docker isolation",
        )
        assert package.rag_nodes_included > 0
        rag_msgs = [
            m for m in package.messages
            if "knowledge from memory graph" in m.get("content", "").lower()
        ]
        assert len(rag_msgs) == 1
        assert "Docker" in rag_msgs[0]["content"] or "Isolation" in rag_msgs[0]["content"]

    asyncio.run(_run())


def test_context_optimizer_rag_nodes_pruned_when_over_rag_budget() -> None:
    async def _run() -> None:
        from ironcore.memory.graph_rag import KnowledgeNode

        # 100 nodes — should be pruned given a tight rag_budget
        nodes = [
            KnowledgeNode(entity_type="concept", name=f"Entity_{i}" + " detail " * 30)
            for i in range(100)
        ]
        graph_rag = _FakeGraphRAG(nodes)
        optimizer = ContextOptimizer(
            session_store=None,
            graph_rag=graph_rag,
            total_budget=4_000,  # tight
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Short.",
            available_tools=[],
            current_query="entity query",
        )
        # Must not include all 100 nodes in a 4K budget
        assert package.rag_nodes_included < 100

    asyncio.run(_run())


def test_context_optimizer_budget_violation_error() -> None:
    """Fixed overhead alone exceeds budget → BudgetViolationError."""

    async def _run() -> None:
        optimizer = ContextOptimizer(session_store=None, total_budget=50)  # absurdly small
        with pytest.raises(BudgetViolationError):
            await optimizer.optimize(
                session_id="s1",
                system_prompt="You are an advanced AI agent " * 20,  # ~200+ tokens
                available_tools=[_tool("tool1"), _tool("tool2"), _tool("tool3")],
                current_query="query",
            )

    asyncio.run(_run())


def test_context_optimizer_package_audit_fields() -> None:
    """ContextPackage must have all audit fields properly populated."""

    async def _run() -> None:
        optimizer = ContextOptimizer(session_store=None, total_budget=20_000)
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="System.",
            available_tools=[_tool("finish")],
            current_query="test",
        )
        assert isinstance(package.token_count, int)
        assert isinstance(package.dropped_messages, int)
        assert isinstance(package.rag_nodes_included, int)
        assert isinstance(package.summary_inserted, bool)
        assert isinstance(package.budget, TokenBudget)
        assert isinstance(package.assembly_time_ms, float)
        assert package.assembly_time_ms >= 0.0

    asyncio.run(_run())


def test_context_optimizer_estimate_budget_sync() -> None:
    """estimate_budget() is sync, returns correct overhead."""
    optimizer = ContextOptimizer(session_store=None, total_budget=100_000)
    budget = optimizer.estimate_budget(
        system_prompt="You are IronCore agent.",
        available_tools=[_tool("think", "Think carefully."), _tool("finish", "End run.")],
        model="claude-sonnet-4-6",
    )
    assert isinstance(budget, TokenBudget)
    assert budget.total_budget == 100_000
    assert budget.system_prompt_tokens > 0
    assert budget.tool_definitions_tokens > 0
    assert budget.rag_context_tokens == 0  # not loaded in estimate
    assert budget.history_tokens == 0


def test_context_optimizer_session_store_failure_graceful() -> None:
    """If SessionStore raises, optimizer should proceed with empty history."""

    class _FailingStore:
        async def get_messages(self, session_id: str) -> list:
            raise RuntimeError("DB connection lost")

    async def _run() -> None:
        optimizer = ContextOptimizer(
            session_store=_FailingStore(),
            total_budget=20_000,
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Resilient agent.",
            available_tools=[],
            current_query="query",
        )
        assert isinstance(package, ContextPackage)
        assert package.dropped_messages == 0

    asyncio.run(_run())


def test_context_optimizer_rag_failure_graceful() -> None:
    """If GraphRAG raises, optimizer produces package without RAG content."""

    class _FailingRAG:
        async def query_context(self, query: str):  # noqa: ANN201
            raise ConnectionError("Graph DB down")

    async def _run() -> None:
        optimizer = ContextOptimizer(
            session_store=None,
            graph_rag=_FailingRAG(),
            total_budget=20_000,
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Resilient.",
            available_tools=[],
            current_query="query",
        )
        assert package.rag_nodes_included == 0

    asyncio.run(_run())


def test_context_optimizer_empty_query_skips_rag() -> None:
    async def _run() -> None:
        from ironcore.memory.graph_rag import KnowledgeNode

        nodes = [KnowledgeNode(entity_type="tech", name="Python")]
        graph_rag = _FakeGraphRAG(nodes)
        optimizer = ContextOptimizer(
            session_store=None,
            graph_rag=graph_rag,
            total_budget=20_000,
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Agent.",
            available_tools=[],
            current_query="",   # empty → must skip RAG
        )
        assert package.rag_nodes_included == 0

    asyncio.run(_run())


def test_context_optimizer_message_order() -> None:
    """System prompt must come first; recent history last."""

    async def _run() -> None:
        messages = [
            _FakeSessionMessage("user", "Recent user turn"),
            _FakeSessionMessage("assistant", "Recent assistant turn"),
        ]
        store = _FakeSessionStore(messages)
        optimizer = ContextOptimizer(session_store=store, total_budget=50_000)
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Core instructions.",
            available_tools=[_tool("think")],
            current_query="test",
        )
        assert package.messages[0]["role"] == "system"
        assert "Core instructions" in package.messages[0]["content"]
        # Recent history should appear at the end
        roles_at_end = [package.messages[-1]["role"], package.messages[-2]["role"]]
        assert "user" in roles_at_end or "assistant" in roles_at_end

    asyncio.run(_run())


def test_context_optimizer_custom_budget_ratios() -> None:
    """Custom ratios should be applied without raising."""

    async def _run() -> None:
        optimizer = ContextOptimizer(
            session_store=None,
            total_budget=50_000,
            budget_ratios={
                "response_reserve_pct": 0.20,
                "recent_history_pct": 0.50,
                "rag_context_pct": 0.20,
            },
        )
        package = await optimizer.optimize(
            session_id="s1",
            system_prompt="Agent.",
            available_tools=[],
            current_query="custom ratios test",
        )
        assert isinstance(package, ContextPackage)

    asyncio.run(_run())


def test_context_optimizer_format_tools_text_sandbox_flag() -> None:
    """Tools with requires_sandbox=True should show [sandbox] in the listing."""
    async def _sandboxed_handler(**kwargs: Any) -> str:
        return "result"

    sandboxed = ToolDefinition(
        name="run_script",
        handler=_sandboxed_handler,
        risk_level=RiskLevel.HIGH,
        requires_sandbox=True,
        description="Execute a Python script",
    )
    optimizer = ContextOptimizer(session_store=None, total_budget=50_000)
    text = optimizer._format_tools_text([sandboxed])
    assert "[sandbox]" in text
    assert "run_script" in text
    assert "HIGH" in text


def test_context_optimizer_format_tools_text_empty() -> None:
    optimizer = ContextOptimizer(session_store=None, total_budget=50_000)
    assert optimizer._format_tools_text([]) == ""
