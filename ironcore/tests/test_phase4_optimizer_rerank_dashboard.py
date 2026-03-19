"""
IronCore V2 — Phase 4 Tests: Reranker + Cost Dashboard
=======================================================

Chạy: python -m pytest tests/test_phase4_optimizer_rerank_dashboard.py -v

Coverage:
  A. BM25Scorer
    - Score documents theo relevance
    - Top-n giới hạn đúng
    - Xử lý empty input
  B. Reranker (BM25 mode — không cần Cohere API)
    - Nhận dạng các keys query và trả đúng order
    - top_n parameter
    - Empty documents
    - Cohere disabled → BM25 mode
  C. CostDashboard
    - record_api_call accumulates đúng
    - get_session_report trả SessionCostReport hợp lệ
    - cache_hits → semantic_cache_hits trong report
    - record_compression_savings → tokens_saved_by_compression
    - get_global_report aggregate nhiều sessions
    - get_time_series trả List[MetricPoint]

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import time
from typing import List

import pytest

from ironcore.optimizer.reranker import BM25Scorer, Reranker, RerankResult
from ironcore.optimizer.cost_dashboard import (
    CostDashboard,
    MetricPoint,
    SessionCostReport,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_reranker_bm25(top_n: int = 5) -> Reranker:
    """Reranker với BM25 mode (no Cohere key)."""
    return Reranker(cohere_api_key=None, top_n=top_n)


DOCS = [
    "IronCore is an AI system that uses GraphRAG memory.",
    "ChromaDB stores vector embeddings for semantic search.",
    "The weather today is sunny with a high of 25 degrees.",
    "Python asyncio enables concurrent coroutine execution.",
    "Claude is an Anthropic language model with a 200K context window.",
    "FastAPI is a modern web framework for building APIs.",
    "This sentence has nothing to do with the query topic.",
    "LLM token costs can be reduced with prompt caching techniques.",
    "NetworkX is a Python library for graph analysis.",
    "The optimizer reduces API costs by caching and compressing prompts.",
]


# ──────────────────────────────────────────────────────────────────────────────
# Test A: BM25Scorer
# ──────────────────────────────────────────────────────────────────────────────


def test_bm25_returns_top_n():
    """BM25 trả về đúng số kết quả yêu cầu."""
    scorer = BM25Scorer()
    results = scorer.score("IronCore memory graph", DOCS, top_n=3)
    assert len(results) == 3


def test_bm25_relevant_first():
    """Document liên quan nhất phải có relevance_score cao nhất."""
    scorer = BM25Scorer()
    results = scorer.score("reduce API token costs caching", DOCS, top_n=5)
    # Doc 7 và 9 nói về reduce cost/caching → phải được rank cao
    top_texts = [r.document for r in results[:3]]
    keyword_matches = sum(
        1 for t in top_texts
        if any(kw in t.lower() for kw in ["cost", "cach", "token", "optimizer", "reduce"])
    )
    assert keyword_matches >= 1, f"Expected cost/cache-related docs in top 3: {top_texts}"


def test_bm25_scores_sorted_descending():
    """BM25 results phải được sort descending theo relevance_score."""
    scorer = BM25Scorer()
    results = scorer.score("chromadb vector embeddings semantic", DOCS, top_n=5)
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_bm25_empty_documents():
    """Empty documents → trả về []."""
    scorer = BM25Scorer()
    results = scorer.score("query", [], top_n=5)
    assert results == []


def test_bm25_index_is_original_position():
    """RerankResult.index phải là position trong documents list ban đầu."""
    scorer = BM25Scorer()
    docs = ["apple banana cherry", "mango papaya avocado", "cherry blossom festival"]
    results = scorer.score("cherry", docs, top_n=3)
    for r in results:
        assert 0 <= r.index < len(docs)
        assert r.document == docs[r.index]


def test_bm25_score_normalized_0_to_1():
    """BM25 scores phải trong khoảng [0, 1]."""
    scorer = BM25Scorer()
    results = scorer.score("python asyncio coroutine", DOCS, top_n=5)
    for r in results:
        assert 0.0 <= r.relevance_score <= 1.0, \
            f"Score {r.relevance_score} out of range"


# ──────────────────────────────────────────────────────────────────────────────
# Test B: Reranker
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reranker_bm25_mode_returns_results():
    """Reranker (BM25 mode) phải trả về List[RerankResult]."""
    reranker = _make_reranker_bm25(top_n=4)
    results = await reranker.rerank("token cost optimization caching", DOCS)
    assert len(results) == 4
    assert all(isinstance(r, RerankResult) for r in results)


@pytest.mark.asyncio
async def test_reranker_top_n_override():
    """Override top_n qua tham số gọi."""
    reranker = _make_reranker_bm25(top_n=10)
    results = await reranker.rerank("query", DOCS, top_n=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_reranker_empty_documents():
    """Empty documents → trả về []."""
    reranker = _make_reranker_bm25()
    results = await reranker.rerank("query", [])
    assert results == []


@pytest.mark.asyncio
async def test_reranker_single_document():
    """Single document → trả về 1 kết quả."""
    reranker = _make_reranker_bm25(top_n=5)
    results = await reranker.rerank("IronCore", ["IronCore is an AI system."])
    assert len(results) == 1


@pytest.mark.asyncio
async def test_reranker_results_sorted_descending():
    """Reranker output phải sorted descending by relevance_score."""
    reranker = _make_reranker_bm25(top_n=5)
    results = await reranker.rerank("semantic memory graphrag chromadb", DOCS)
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_reranker_is_anthropic_not_api():
    """BM25 mode (no API key) → tất cả documents vẫn được xử lý."""
    reranker = Reranker(cohere_api_key=None, top_n=3)
    assert reranker._cohere_available is False
    results = await reranker.rerank("asyncio python concurrent", DOCS)
    assert len(results) == 3


# ──────────────────────────────────────────────────────────────────────────────
# Test C: CostDashboard
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_record_and_report():
    """record_api_call → get_session_report có đúng total_api_calls."""
    dashboard = CostDashboard()
    session_id = "test-session-001"

    await dashboard.record_api_call(
        session_id=session_id,
        tokens_used=1000,
        cost_usd=0.003,
        model_id="claude-sonnet-4-6",
        cache_hit=False,
        tokens_received=500,
    )
    await dashboard.record_api_call(
        session_id=session_id,
        tokens_used=800,
        cost_usd=0.0024,
        model_id="claude-sonnet-4-6",
        cache_hit=True,  # Cache hit
        tokens_received=400,
    )

    report = await dashboard.get_session_report(session_id)
    assert report.total_api_calls == 2
    assert report.semantic_cache_hits == 1
    assert report.tokens_sent == 1800
    assert report.total_cost_usd == pytest.approx(0.0054, abs=1e-7)


@pytest.mark.asyncio
async def test_dashboard_cache_hit_rate():
    """semantic_cache_hit_rate tính đúng."""
    dashboard = CostDashboard()
    session_id = "test-session-002"

    # 3 calls, 2 cache hits → hit_rate = 0.667
    for i in range(3):
        await dashboard.record_api_call(
            session_id=session_id,
            tokens_used=500,
            cost_usd=0.001,
            model_id="claude-haiku",
            cache_hit=(i < 2),  # First 2 are hits
        )

    report = await dashboard.get_session_report(session_id)
    assert report.semantic_cache_hit_rate == pytest.approx(2 / 3, abs=0.01)


@pytest.mark.asyncio
async def test_dashboard_compression_savings():
    """record_compression_savings → tokens_saved_by_compression trong report."""
    dashboard = CostDashboard()
    session_id = "test-session-003"

    await dashboard.record_api_call(
        session_id=session_id,
        tokens_used=1000,
        cost_usd=0.002,
        model_id="gpt-4o",
        cache_hit=False,
    )
    await dashboard.record_compression_savings(session_id=session_id, tokens_saved=350)

    report = await dashboard.get_session_report(session_id)
    assert report.tokens_saved_by_compression == 350


@pytest.mark.asyncio
async def test_dashboard_kv_cache_tracking():
    """kv_cache_read_tokens → tracked correctly trong report."""
    dashboard = CostDashboard()
    session_id = "test-session-004"

    await dashboard.record_api_call(
        session_id=session_id,
        tokens_used=200,
        cost_usd=0.0005,
        model_id="claude-sonnet",
        cache_hit=False,
        kv_cache_read_tokens=2000,  # Anthropic KV-cache
    )

    report = await dashboard.get_session_report(session_id)
    assert report.kv_cache_hit_rate == pytest.approx(1.0, abs=0.01)
    # tokens_saved_by_kv_cache = 2000 * 0.90 = 1800
    assert report.tokens_saved_by_kv_cache == 1800


@pytest.mark.asyncio
async def test_dashboard_global_report_aggregates_sessions():
    """get_global_report aggregate tất cả sessions."""
    dashboard = CostDashboard()

    for i in range(3):
        await dashboard.record_api_call(
            session_id=f"session-{i}",
            tokens_used=1000,
            cost_usd=0.002,
            model_id="claude-haiku",
            cache_hit=False,
        )

    global_report = await dashboard.get_global_report(hours=24)
    assert global_report.total_api_calls == 3
    assert global_report.total_cost_usd == pytest.approx(0.006, abs=1e-8)


@pytest.mark.asyncio
async def test_dashboard_time_series_returns_points():
    """get_time_series trả về List[MetricPoint]."""
    dashboard = CostDashboard()
    session_id = "test-session-005"

    for _ in range(5):
        await dashboard.record_api_call(
            session_id=session_id,
            tokens_used=500,
            cost_usd=0.001,
            model_id="claude-sonnet",
            cache_hit=False,
        )

    points = await dashboard.get_time_series(metric="cost", hours=24)
    assert isinstance(points, list)
    assert all(isinstance(p, MetricPoint) for p in points)


@pytest.mark.asyncio
async def test_dashboard_savings_pct_property():
    """SessionCostReport.savings_pct tính đúng."""
    report = SessionCostReport(
        session_id="test",
        start_time=time.time(),
        duration_seconds=100.0,
        total_cost_usd=0.006,
        estimated_without_optimizer_usd=0.010,
    )
    assert report.savings_usd == pytest.approx(0.004, abs=1e-8)
    assert report.savings_pct == pytest.approx(40.0, abs=0.01)
