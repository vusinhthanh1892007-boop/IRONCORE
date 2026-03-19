"""
IronCore V2 — Phase 1 Tests: Semantic Cache
============================================
Tests cho ironcore/optimizer/semantic_cache.py

Chạy: python -m pytest tests/test_phase1_optimizer_cache.py -v

Test coverage:
  - Exact same query → cache hit
  - Semantically similar query → cache hit (similarity >= 0.92)
  - Different query → cache miss
  - TTL expired → cache miss
  - Namespace isolation (hit trong A không ảnh hưởng B)
  - LRU eviction khi đầy
  - embedding model unavailable → graceful bypass (trả None)
  - invalidate_namespace xóa đúng namespace
  - get_stats trả về số liệu chính xác

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ironcore.optimizer.semantic_cache import (
    CacheStats,
    CachedResponse,
    SemanticCache,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _make_mock_embedding(value: float = 0.5, dim: int = 384) -> list:
    """Tạo embedding giả với các giá trị đồng nhất."""
    return [value] * dim


def _make_ready_cache(
    similarity_threshold: float = 0.92,
    max_entries: int = 100,
    default_ttl: int = 3600,
) -> tuple[SemanticCache, MagicMock]:
    """
    Tạo SemanticCache với ChromaDB và SentenceTransformer đã mock sẵn.
    Trả về (cache, mock_collection).
    """
    cache = SemanticCache(
        similarity_threshold=similarity_threshold,
        max_entries_per_namespace=max_entries,
        default_ttl_seconds=default_ttl,
    )

    # Mock collection
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": [], "documents": []}
    mock_collection.query.return_value = {
        "ids": [[]],
        "distances": [[]],
        "metadatas": [[]],
        "documents": [[]],
    }

    # Mock embedding model
    mock_encoder = MagicMock()
    mock_encoder.get_sentence_embedding_dimension.return_value = 384

    import numpy as np
    mock_encoder.encode.return_value = np.array(_make_mock_embedding(0.5))

    cache._embedding_model = mock_encoder
    cache._collection = mock_collection
    cache._chroma_client = MagicMock()
    cache._initialized = True

    return cache, mock_collection


# ──────────────────────────────────────────────────────────────────────────────
# Test: Cache Hit — Exact Same Query
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_same_query_cache_hit():
    """
    Cùng một query chính xác → cache hit với similarity = 1.0.
    """
    cache, mock_collection = _make_ready_cache()

    # Setup mock: query trả về 1 result với distance 0.0 (identical)
    now = time.time()
    mock_collection.query.return_value = {
        "ids": [["ns_abc123"]],
        "distances": [[0.0]],   # distance 0 = similarity 1.0
        "metadatas": [[{
            "namespace": "chat",
            "query_hash": "abc123",
            "created_at": now - 10,
            "expires_at": now + 3590,
            "hit_count": 0,
            "response_tokens": 50,
            "source_model": "claude-sonnet-4-6",
        }]],
        "documents": [["This is the cached response."]],
    }

    result = await cache.lookup("Tóm tắt bài đăng này", namespace="chat")

    assert result is not None
    assert isinstance(result, CachedResponse)
    assert result.cached is True
    assert result.similarity_score >= 0.92
    assert result.response == "This is the cached response."
    assert result.source_model == "claude-sonnet-4-6"


# ──────────────────────────────────────────────────────────────────────────────
# Test: Cache Hit — Semantically Similar Query
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_semantically_similar_query_cache_hit():
    """
    Query khác từ ngữ nhưng tương đồng ngữ nghĩa → cache hit (similarity >= 0.92).
    """
    cache, mock_collection = _make_ready_cache(similarity_threshold=0.92)

    now = time.time()
    # distance = 0.08 → similarity = 1 - 0.08 = 0.92 (đúng ngưỡng)
    mock_collection.query.return_value = {
        "ids": [["chat_xyz789"]],
        "distances": [[0.08]],
        "metadatas": [[{
            "namespace": "chat",
            "query_hash": "xyz789",
            "created_at": now - 60,
            "expires_at": now + 3540,
            "hit_count": 2,
            "response_tokens": 80,
            "source_model": "ollama/llama3.1",
        }]],
        "documents": [["Bitcoin hiện tại đang ở mức $65,000."]],
    }

    result = await cache.lookup("BTC bao nhiêu tiền vậy?", namespace="chat")

    assert result is not None
    assert result.similarity_score >= 0.92
    assert result.hit_count == 3  # 2 + 1 từ lần lookup này


# ──────────────────────────────────────────────────────────────────────────────
# Test: Cache Miss — Different Query
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_different_query_cache_miss():
    """
    Query hoàn toàn khác → cache miss (similarity thấp hơn threshold).
    """
    cache, mock_collection = _make_ready_cache(similarity_threshold=0.92)

    now = time.time()
    # distance = 0.4 → similarity = 0.6, thấp hơn 0.92 → miss
    mock_collection.query.return_value = {
        "ids": [["chat_aabbcc"]],
        "distances": [[0.4]],
        "metadatas": [[{
            "namespace": "chat",
            "query_hash": "aabbcc",
            "created_at": now - 300,
            "expires_at": now + 3300,
            "hit_count": 0,
            "response_tokens": 60,
            "source_model": "claude-sonnet-4-6",
        }]],
        "documents": [["Hướng dẫn cài Docker step by step."]],
    }

    result = await cache.lookup("Cách cài đặt Git trên Ubuntu", namespace="chat")

    assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# Test: Cache Miss — TTL Expired
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ttl_expired_cache_miss():
    """
    Entry đã hết TTL → trả về None và xóa entry khỏi ChromaDB.
    """
    cache, mock_collection = _make_ready_cache()
    mock_collection.delete = MagicMock()

    now = time.time()
    # expires_at trong quá khứ → đã hết TTL
    mock_collection.query.return_value = {
        "ids": [["chat_expired"]],
        "distances": [[0.01]],  # similarity rất cao nhưng đã hết hạn
        "metadatas": [[{
            "namespace": "chat",
            "query_hash": "expired123",
            "created_at": now - 7200,
            "expires_at": now - 100,  # hết hạn 100 giây trước
            "hit_count": 5,
            "response_tokens": 40,
            "source_model": "claude-haiku-3-5",
        }]],
        "documents": [["Response cũ đã hết hạn."]],
    }

    result = await cache.lookup("câu hỏi nào đó", namespace="chat")

    assert result is None
    # Phải gọi delete để dọn entry hết hạn
    mock_collection.delete.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Test: Namespace Isolation
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_namespace_isolation():
    """
    Cache hit trong namespace 'chat' không ảnh hưởng namespace 'rag_query'.
    ChromaDB query phải được gọi với where filter cho đúng namespace.
    """
    cache, mock_collection = _make_ready_cache()

    # Namespace "rag_query" không có kết quả
    mock_collection.query.return_value = {
        "ids": [[]],
        "distances": [[]],
        "metadatas": [[]],
        "documents": [[]],
    }

    result = await cache.lookup("câu hỏi rag", namespace="rag_query")
    assert result is None

    # Kiểm tra ChromaDB được gọi với namespace filter đúng
    call_kwargs = mock_collection.query.call_args
    assert call_kwargs is not None
    where_filter = call_kwargs[1].get("where") or call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
    # Lấy keyword argument "where"
    actual_where = mock_collection.query.call_args.kwargs.get("where") or {}
    assert actual_where.get("namespace") == "rag_query"


# ──────────────────────────────────────────────────────────────────────────────
# Test: LRU Eviction
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lru_eviction_when_full():
    """
    Khi namespace đạt max_entries → evict 10% cũ nhất trước khi store mới.
    """
    # max_entries=5 để test dễ
    cache, mock_collection = _make_ready_cache(max_entries=5)

    now = time.time()
    # Giả lập namespace đã có 5 entries (đầy)
    existing_ids = [f"chat_entry{i}" for i in range(5)]
    existing_metas = [
        {"namespace": "chat", "created_at": now - (5 - i) * 100}
        for i in range(5)
    ]
    mock_collection.get.return_value = {
        "ids": existing_ids,
        "metadatas": existing_metas,
    }
    mock_collection.upsert = MagicMock()
    mock_collection.delete = MagicMock()

    await cache.store(
        query="new query",
        response="new response",
        namespace="chat",
    )

    # delete phải được gọi để evict entry cũ
    mock_collection.delete.assert_called()
    deleted_ids = mock_collection.delete.call_args[1].get("ids") or mock_collection.delete.call_args[0][0]
    assert len(deleted_ids) >= 1  # Ít nhất 1 entry bị xóa (10% của 5 = 1)
    # Entry bị xóa phải là cũ nhất (created_at nhỏ nhất = entry0)
    assert "chat_entry0" in deleted_ids


# ──────────────────────────────────────────────────────────────────────────────
# Test: Embedding Unavailable → Graceful Skip
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embedding_unavailable_graceful_skip():
    """
    Nếu embedding model chưa sẵn sàng → lookup/store trả về None/None mà không crash.
    """
    # Cache chưa initialize (embedding model = None)
    cache = SemanticCache()
    # Không gọi initialize() → _initialized = False

    result = await cache.lookup("bất kỳ query nào")
    assert result is None  # Không crash

    # store cũng không crash
    await cache.store("query", "response")  # Không raise exception


# ──────────────────────────────────────────────────────────────────────────────
# Test: invalidate_namespace
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidate_namespace_removes_all_entries():
    """
    invalidate_namespace("plugin:foo") xóa toàn bộ entries trong namespace đó.
    """
    cache, mock_collection = _make_ready_cache()

    mock_collection.get.return_value = {
        "ids": ["plugin:foo_e1", "plugin:foo_e2", "plugin:foo_e3"],
        "metadatas": [],
    }
    mock_collection.delete = MagicMock()

    count = await cache.invalidate_namespace("plugin:foo")

    assert count == 3
    mock_collection.delete.assert_called_once()
    deleted_ids = mock_collection.delete.call_args.kwargs.get("ids") or []
    assert set(deleted_ids) == {"plugin:foo_e1", "plugin:foo_e2", "plugin:foo_e3"}


@pytest.mark.asyncio
async def test_invalidate_namespace_empty_returns_zero():
    """Namespace rỗng → trả về 0, không gọi delete."""
    cache, mock_collection = _make_ready_cache()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}
    mock_collection.delete = MagicMock()

    count = await cache.invalidate_namespace("empty_namespace")

    assert count == 0
    mock_collection.delete.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Test: get_stats
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_stats_returns_accurate_data():
    """
    get_stats() phải trả về CacheStats với total_entries, hit_rate, tokens_saved chính xác.
    """
    cache, mock_collection = _make_ready_cache()

    now = time.time()
    mock_collection.get.return_value = {
        "ids": ["e1", "e2"],
        "metadatas": [
            {
                "namespace": "chat",
                "query_hash": "hash1",
                "created_at": now - 500,
                "hit_count": 10,
                "response_tokens": 100,
            },
            {
                "namespace": "chat",
                "query_hash": "hash2",
                "created_at": now - 200,
                "hit_count": 5,
                "response_tokens": 80,
            },
        ],
    }
    # Giả lập 8 hits và 2 misses
    cache._hit_counts["chat"] = 8
    cache._miss_counts["chat"] = 2

    stats = await cache.get_stats("chat")

    assert isinstance(stats, CacheStats)
    assert stats.namespace == "chat"
    assert stats.total_entries == 2
    assert stats.hit_count_total == 15        # 10 + 5
    assert stats.estimated_tokens_saved == 1400  # 100*10 + 80*5
    assert stats.hit_rate == pytest.approx(0.8, abs=0.01)   # 8/(8+2)


# ──────────────────────────────────────────────────────────────────────────────
# Test: store + lookup roundtrip (integration-style)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_does_not_raise_on_valid_input():
    """
    store() với input hợp lệ → không raise bất kỳ exception nào.
    """
    cache, mock_collection = _make_ready_cache()
    mock_collection.upsert = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    # Không nên raise exception
    await cache.store(
        query="Hướng dẫn cài đặt Python",
        response='{"tool_name": "think", "args": {"thought": "..."}}',
        namespace="chat",
        ttl=1800,
        source_model="claude-sonnet-4-6",
        metadata={"session_id": "sess-001", "complexity": "complex"},
    )

    mock_collection.upsert.assert_called_once()
    upsert_call = mock_collection.upsert.call_args.kwargs
    assert upsert_call["metadatas"][0]["namespace"] == "chat"
    assert upsert_call["metadatas"][0]["source_model"] == "claude-sonnet-4-6"
    assert upsert_call["metadatas"][0]["ext_session_id"] == "sess-001"


@pytest.mark.asyncio
async def test_store_with_no_ttl_sets_no_expiry():
    """
    store() với ttl=0 → expires_at = 0 (không hết hạn).
    """
    cache, mock_collection = _make_ready_cache(default_ttl=0)
    mock_collection.upsert = MagicMock()
    mock_collection.get.return_value = {"ids": [], "metadatas": []}

    await cache.store("query", "response", ttl=0)

    upsert_call = mock_collection.upsert.call_args.kwargs
    assert upsert_call["metadatas"][0]["expires_at"] == 0.0
