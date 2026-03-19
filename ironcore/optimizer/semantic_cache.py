"""
IronCore Optimizer — Phase 1: Semantic Cache
=============================================
Claude 4.6 "The Optimizer" — IronCore V2

Xây dựng lớp cache ngữ nghĩa — khi hai query khác nhau về từ ngữ
nhưng giống nhau về ý nghĩa, trả về response từ cache thay vì gọi API.

Tiết kiệm: 30–50% API calls cho các query lặp lại.

Backend: ChromaDB (đã có trong requirements) + sentence-transformers
Embedding model: all-MiniLM-L6-v2 (384-dim, local, nhẹ, nhanh)
Similarity metric: Cosine similarity
Threshold mặc định: 0.92 (cao để tránh false positive)

Interface contract (cung cấp cho Gemini 3.1):
    SemanticCache.lookup(query, namespace) -> Optional[CachedResponse]
    SemanticCache.store(query, response, namespace, ttl, ...)
    SemanticCache.invalidate_namespace(namespace) -> int

Interface contract (cung cấp qua LLMBridge cho GPT-5.4 metrics):
    SemanticCache.get_stats(namespace) -> CacheStats

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class OptimizerError(Exception):
    """Base exception for all Optimizer module errors."""


class CacheError(OptimizerError):
    """Raised when a cache operation fails unrecoverably."""


# ──────────────────────────────────────────────────────────────────────────────
# Data Models (Pydantic V2)
# ──────────────────────────────────────────────────────────────────────────────


class CacheEntry(BaseModel):
    """One entry stored inside the semantic cache."""

    key_hash: str                           # SHA-256 của normalized query
    query_embedding: List[float]            # Vector 384-dim (MiniLM)
    response: str                           # Cached LLM response
    response_tokens: int                    # Token count ước tính của response
    namespace: str = "default"             # Phân chia theo use-case
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default=0.0)  # Unix timestamp; 0 = không hết hạn
    hit_count: int = 0                      # Số lần được serve từ cache
    source_model: str = ""                  # Model nào tạo ra response này
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CachedResponse(BaseModel):
    """
    Kết quả trả về khi cache hit.
    Được cung cấp cho LLMBridge để build Action mà không gọi API.
    """

    response: str
    cached: bool = True
    similarity_score: float                 # 0.0–1.0, độ tương đồng với query gốc
    original_query_hash: str
    age_seconds: float                      # Bao lâu response đã được cache
    hit_count: int
    response_tokens: int = 0
    source_model: str = ""


class CacheStats(BaseModel):
    """Thống kê hoạt động cache — được GPT-5.4 hiển thị lên Dashboard."""

    namespace: str
    total_entries: int = 0
    hit_count_total: int = 0               # Tổng số lần cache được serve
    miss_count: int = 0                    # Lần lookup không tìm thấy
    hit_rate: float = 0.0                  # hit_count / (hit + miss), 0.0–1.0
    estimated_tokens_saved: int = 0        # Tokens tiết kiệm được
    oldest_entry_age_seconds: float = 0.0
    most_hit_query_hash: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# SemanticCache
# ──────────────────────────────────────────────────────────────────────────────


class SemanticCache:
    """
    Semantic similarity-based LLM response cache.

    Sử dụng ChromaDB làm vector store và sentence-transformers để embed query.
    Hai câu hỏi có cosine similarity >= threshold được coi là "giống nhau"
    và chia sẻ response từ cache.

    Ví dụ:
        "Tóm tắt bài đăng này" và "Cho tôi xem tóm tắt của bài này" → SAME
        "Giá Bitcoin hôm nay?" và "BTC bao nhiêu tiền vậy?" → SAME
        "Hướng dẫn cài Docker" và "Cách cài đặt Git" → DIFFERENT

    Thread Safety:
        Mọi method đều async. ChromaDB client là thread-safe.
        Mỗi namespace có collection riêng trong cùng một ChromaDB.

    Usage::
        cache = SemanticCache()
        await cache.initialize()

        # Trong LLMBridge.get_next_action():
        hit = await cache.lookup(user_query, namespace="chat")
        if hit:
            return parse_action_from_cached(hit.response)

        response = await call_llm(...)
        await cache.store(user_query, response.content, namespace="chat",
                          source_model=model_id, metadata={"session_id": sid})
    """

    # ChromaDB collection name — chứa TẤT CẢ namespaces (phân biệt bằng metadata filter)
    _COLLECTION_NAME = "ironcore_semantic_cache"

    def __init__(
        self,
        similarity_threshold: float = 0.92,
        max_entries_per_namespace: int = 10_000,
        default_ttl_seconds: int = 3_600,
        embedding_model: str = "all-MiniLM-L6-v2",
        chroma_persist_dir: Optional[str] = None,
    ) -> None:
        """
        Args:
            similarity_threshold:     Ngưỡng cosine similarity để xác định cache hit.
                                      Mặc định 0.92 — cao để tránh false positive.
            max_entries_per_namespace: Số entries tối đa mỗi namespace. LRU eviction.
            default_ttl_seconds:      TTL mặc định (giây). 0 = không hết hạn.
            embedding_model:          sentence-transformers model name.
            chroma_persist_dir:       Thư mục lưu ChromaDB. None = ~/.ironcore/cache/
        """
        self._threshold = similarity_threshold
        self._max_entries = max_entries_per_namespace
        self._default_ttl = default_ttl_seconds
        self._embedding_model_name = embedding_model

        # Resolve persist path
        if chroma_persist_dir is None:
            chroma_persist_dir = str(
                os.path.join(os.path.expanduser("~"), ".ironcore", "cache")
            )
        self._chroma_dir = chroma_persist_dir

        # Lazy-loaded components (chỉ khởi tạo khi first call)
        self._embedding_model: Optional[Any] = None      # SentenceTransformer
        self._chroma_client: Optional[Any] = None        # chromadb.Client
        self._collection: Optional[Any] = None           # chromadb.Collection
        self._initialized = False
        self._cleanup_task: Optional[asyncio.Task] = None

        # Hit/miss counters per namespace (in-memory, reset on restart)
        self._hit_counts: Dict[str, int] = {}
        self._miss_counts: Dict[str, int] = {}

        logger.info(
            "[SemanticCache] Created | threshold=%.2f max_entries=%d ttl=%ds model=%s",
            similarity_threshold,
            max_entries_per_namespace,
            default_ttl_seconds,
            embedding_model,
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """
        Khởi tạo ChromaDB collection và embedding model.
        Idempotent — gọi nhiều lần không sao.
        Chạy background TTL cleanup task (mỗi 5 phút).
        """
        if self._initialized:
            return

        try:
            # Lazy import để không break khi chưa cài package
            import chromadb
            from sentence_transformers import SentenceTransformer

            os.makedirs(self._chroma_dir, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(path=self._chroma_dir)

            # Tạo hoặc lấy collection
            self._collection = self._chroma_client.get_or_create_collection(
                name=self._COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},  # Cosine similarity
            )

            # Load embedding model (nặng ~90MB lần đầu, cache sau đó)
            logger.info(
                "[SemanticCache] Loading embedding model '%s' …",
                self._embedding_model_name,
            )
            self._embedding_model = SentenceTransformer(self._embedding_model_name)
            logger.info(
                "[SemanticCache] Embedding model loaded | dim=%d",
                self._embedding_model.get_sentence_embedding_dimension(),
            )

            self._initialized = True

            # Khởi chạy nền cleanup TTL mỗi 5 phút
            self._cleanup_task = asyncio.create_task(self._ttl_cleanup_loop())
            logger.info(
                "[SemanticCache] Ready | chroma_dir=%s collection=%s",
                self._chroma_dir,
                self._COLLECTION_NAME,
            )

        except ImportError as exc:
            logger.error(
                "[SemanticCache] Missing dependency: %s. "
                "Install with: pip install chromadb sentence-transformers",
                exc,
            )
            # Không raise — cache sẽ bị bypass gracefully
        except Exception as exc:
            logger.error("[SemanticCache] Initialization failed: %s", exc)
            # Không raise — cache bypass gracefully

    async def close(self) -> None:
        """Dừng background cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._initialized = False
        logger.info("[SemanticCache] Closed.")

    # ── Core API ──────────────────────────────────────────────────────────────

    async def lookup(
        self,
        query: str,
        namespace: str = "default",
    ) -> Optional[CachedResponse]:
        """
        Tìm response trong cache cho một query.

        Nếu tìm thấy entry có similarity >= threshold VÀ chưa hết TTL
        → trả về CachedResponse.
        Ngược lại → trả về None (caller tiếp tục gọi LLM bình thường).

        Edge case: nếu embedding model unavailable → skip cache, return None.

        Args:
            query:     Query text từ user.
            namespace: Namespace để tách cache theo use-case (chat, rag_query, ...).

        Returns:
            CachedResponse nếu cache hit, None nếu miss.
        """
        if not self._is_ready():
            return None

        t_start = time.monotonic()
        query_norm = self._normalize_query(query)
        query_hash = self._hash_query(query_norm)

        try:
            embedding = await self._embed(query_norm)
            if embedding is None:
                return None

            # Query ChromaDB với where filter cho namespace + chưa expire
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=1,
                where={"namespace": namespace},
                include=["metadatas", "distances", "documents"],
            )

            if not results["ids"] or not results["ids"][0]:
                self._record_miss(namespace)
                logger.debug(
                    "[SemanticCache] Miss (empty results) | namespace=%s hash=%s",
                    namespace,
                    query_hash[:8],
                )
                return None

            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert sang similarity: similarity = 1 - distance (với cosine space trong chroma distance [0,2])
            # Thực ra chromadb với hnsw:space=cosine trả về distance trong [0, 2]:
            # similarity = 1 - (distance / 2) ... nhưng chuẩn xác hơn:
            # distance = 1 - cosine_similarity → similarity = 1 - distance
            distance = results["distances"][0][0]
            similarity = 1.0 - distance  # distance range [0,1] với cosine space

            meta = results["metadatas"][0][0]
            chroma_id = results["ids"][0][0]
            doc = results["documents"][0][0]

            # Kiểm tra TTL
            expires_at = float(meta.get("expires_at", 0))
            if expires_at > 0 and time.time() > expires_at:
                logger.debug(
                    "[SemanticCache] Miss (TTL expired) | namespace=%s id=%s",
                    namespace,
                    chroma_id[:8],
                )
                # Xóa entry hết hạn ngay
                await asyncio.to_thread(self._collection.delete, ids=[chroma_id])
                self._record_miss(namespace)
                return None

            if similarity < self._threshold:
                latency_ms = (time.monotonic() - t_start) * 1_000
                self._record_miss(namespace)
                logger.debug(
                    "[SemanticCache] Miss | namespace=%s similarity=%.3f < threshold=%.2f "
                    "latency=%.1fms",
                    namespace,
                    similarity,
                    self._threshold,
                    latency_ms,
                )
                return None

            # ── CACHE HIT ─────────────────────────────────────────────────
            latency_ms = (time.monotonic() - t_start) * 1_000
            hit_count = int(meta.get("hit_count", 0)) + 1
            age_seconds = time.time() - float(meta.get("created_at", time.time()))

            # Cập nhật hit_count trong ChromaDB (non-blocking)
            new_meta = dict(meta)
            new_meta["hit_count"] = hit_count
            asyncio.create_task(
                asyncio.to_thread(
                    self._collection.update,
                    ids=[chroma_id],
                    metadatas=[new_meta],
                )
            )

            self._record_hit(namespace)
            logger.info(
                "[SemanticCache] HIT | namespace=%s query_hash=%s "
                "similarity=%.3f age=%.0fs hits=%d latency=%.1fms",
                namespace,
                query_hash[:8],
                similarity,
                age_seconds,
                hit_count,
                latency_ms,
            )

            return CachedResponse(
                response=doc,
                cached=True,
                similarity_score=round(similarity, 4),
                original_query_hash=meta.get("query_hash", query_hash),
                age_seconds=round(age_seconds, 1),
                hit_count=hit_count,
                response_tokens=int(meta.get("response_tokens", 0)),
                source_model=meta.get("source_model", ""),
            )

        except Exception as exc:
            logger.error("[SemanticCache] lookup error: %s", exc, exc_info=True)
            return None

    async def store(
        self,
        query: str,
        response: str,
        namespace: str = "default",
        ttl: int = -1,
        source_model: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Lưu một response vào cache.

        Nếu namespace đã đạt max_entries → evict entry cũ nhất (LRU).

        Args:
            query:        Query text từ user.
            response:     LLM response text để cache.
            namespace:    Namespace.
            ttl:          Thời gian sống (giây). -1 = dùng default_ttl.
            source_model: Model ID đã tạo ra response.
            metadata:     Extra context (session_id, complexity, ...).
        """
        if not self._is_ready():
            return

        query_norm = self._normalize_query(query)
        query_hash = self._hash_query(query_norm)
        ttl_seconds = ttl if ttl >= 0 else self._default_ttl
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds > 0 else 0.0
        response_tokens = self._estimate_tokens(response)

        try:
            embedding = await self._embed(query_norm)
            if embedding is None:
                return

            # Kiểm tra + evict nếu đầy
            await self._maybe_evict(namespace)

            chroma_id = f"{namespace}_{query_hash}"
            meta: Dict[str, Any] = {
                "namespace": namespace,
                "query_hash": query_hash,
                "created_at": now,
                "expires_at": expires_at,
                "hit_count": 0,
                "response_tokens": response_tokens,
                "source_model": source_model,
            }
            if metadata:
                # Chỉ giữ scalar values (ChromaDB không support nested dict trong metadata)
                for k, v in metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        meta[f"ext_{k}"] = v

            await asyncio.to_thread(
                self._collection.upsert,
                ids=[chroma_id],
                embeddings=[embedding],
                documents=[response],
                metadatas=[meta],
            )

            logger.info(
                "[SemanticCache] STORE | namespace=%s hash=%s tokens=%d "
                "ttl=%ds model=%s",
                namespace,
                query_hash[:8],
                response_tokens,
                ttl_seconds,
                source_model or "unknown",
            )

        except Exception as exc:
            logger.error("[SemanticCache] store error: %s", exc, exc_info=True)

    async def invalidate(
        self,
        query: str,
        namespace: str = "default",
        similarity_threshold: float = 0.95,
    ) -> bool:
        """
        Xóa entries có similarity > 0.95 với query trong namespace.

        Returns:
            True nếu có ít nhất một entry bị xóa.
        """
        if not self._is_ready():
            return False

        try:
            query_norm = self._normalize_query(query)
            embedding = await self._embed(query_norm)
            if embedding is None:
                return False

            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=10,
                where={"namespace": namespace},
                include=["distances"],
            )

            ids_to_delete = [
                doc_id
                for doc_id, distance in zip(
                    results["ids"][0], results["distances"][0]
                )
                if (1.0 - distance) >= similarity_threshold
            ]

            if ids_to_delete:
                await asyncio.to_thread(self._collection.delete, ids=ids_to_delete)
                logger.info(
                    "[SemanticCache] Invalidated %d entries | namespace=%s",
                    len(ids_to_delete),
                    namespace,
                )
                return True

            return False

        except Exception as exc:
            logger.error("[SemanticCache] invalidate error: %s", exc, exc_info=True)
            return False

    async def invalidate_namespace(self, namespace: str) -> int:
        """
        Xóa toàn bộ entries trong một namespace.
        Được Gemini 3.1 gọi khi plugin mới được cài.

        Returns:
            Số entries đã xóa.
        """
        if not self._is_ready():
            return 0

        try:
            # Lấy tất cả IDs trong namespace
            results = self._collection.get(
                where={"namespace": namespace},
                include=[],
            )
            ids = results.get("ids", [])

            if ids:
                await asyncio.to_thread(self._collection.delete, ids=ids)
                logger.info(
                    "[SemanticCache] Namespace '%s' cleared | %d entries removed",
                    namespace,
                    len(ids),
                )
                # Reset in-memory counters
                self._hit_counts.pop(namespace, None)
                self._miss_counts.pop(namespace, None)

            return len(ids)

        except Exception as exc:
            logger.error(
                "[SemanticCache] invalidate_namespace error: %s", exc, exc_info=True
            )
            return 0

    async def get_stats(self, namespace: str = "default") -> CacheStats:
        """
        Trả về thống kê cho một namespace.
        Được expose qua CostDashboard để GPT-5.4 hiển thị lên UI.

        Args:
            namespace: Namespace cần lấy stats.

        Returns:
            CacheStats object.
        """
        if not self._is_ready():
            return CacheStats(namespace=namespace)

        try:
            results = self._collection.get(
                where={"namespace": namespace},
                include=["metadatas"],
            )
            metadatas = results.get("metadatas", [])
            total = len(metadatas)

            if total == 0:
                return CacheStats(namespace=namespace)

            total_hits = sum(int(m.get("hit_count", 0)) for m in metadatas)
            total_tokens_saved = sum(
                int(m.get("response_tokens", 0)) * int(m.get("hit_count", 0))
                for m in metadatas
            )

            now = time.time()
            oldest_age = max(
                (now - float(m.get("created_at", now)) for m in metadatas),
                default=0.0,
            )

            # Most-hit entry
            best_meta = max(
                metadatas, key=lambda m: int(m.get("hit_count", 0)), default={}
            )
            most_hit_hash = str(best_meta.get("query_hash", ""))

            hit = self._hit_counts.get(namespace, 0)
            miss = self._miss_counts.get(namespace, 0)
            total_lookups = hit + miss
            hit_rate = (hit / total_lookups) if total_lookups > 0 else 0.0

            return CacheStats(
                namespace=namespace,
                total_entries=total,
                hit_count_total=total_hits,
                miss_count=miss,
                hit_rate=round(hit_rate, 4),
                estimated_tokens_saved=total_tokens_saved,
                oldest_entry_age_seconds=round(oldest_age, 1),
                most_hit_query_hash=most_hit_hash[:12] if most_hit_hash else "",
            )

        except Exception as exc:
            logger.error("[SemanticCache] get_stats error: %s", exc, exc_info=True)
            return CacheStats(namespace=namespace)

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _is_ready(self) -> bool:
        """Trả về True nếu cache đã initialize thành công."""
        return (
            self._initialized
            and self._embedding_model is not None
            and self._collection is not None
        )

    @staticmethod
    def _normalize_query(query: str) -> str:
        """
        Chuẩn hóa query trước khi embed và hash:
        - Lowercase
        - Strip whitespace thừa
        - Loại bỏ dấu câu ở đầu/cuối không ảnh hưởng nghĩa
        """
        return " ".join(query.lower().strip().split())

    @staticmethod
    def _hash_query(normalized_query: str) -> str:
        """SHA-256 hash của normalized query — dùng làm ChromaDB document ID."""
        return hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()

    async def _embed(self, text: str) -> Optional[List[float]]:
        """
        Embed text thành vector bằng SentenceTransformer.
        Chạy trong thread pool để không block event loop (model.encode là sync).

        Returns:
            List[float] embedding, hoặc None nếu lỗi.
        """
        try:
            embedding = await asyncio.to_thread(
                self._embedding_model.encode,  # type: ignore[union-attr]
                text,
                normalize_embeddings=True,
            )
            return embedding.tolist()
        except Exception as exc:
            logger.error("[SemanticCache] embed error: %s", exc)
            return None

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        Ước tính số token trong text (approximation: ~4 chars/token).
        Không dùng tokenizer nặng — chỉ cần approximate cho metrics.
        """
        return max(1, len(text) // 4)

    async def _maybe_evict(self, namespace: str) -> None:
        """
        Nếu namespace đã đạt max_entries → xóa entry cũ nhất (LRU by created_at).
        """
        try:
            results = self._collection.get(
                where={"namespace": namespace},
                include=["metadatas"],
            )
            ids = results.get("ids", [])
            if len(ids) < self._max_entries:
                return

            # Sắp xếp theo created_at ascending → xóa batch 10% cũ nhất
            metadatas = results.get("metadatas", [])
            paired = sorted(
                zip(ids, metadatas),
                key=lambda x: float(x[1].get("created_at", 0)),
            )
            evict_count = max(1, int(self._max_entries * 0.10))  # Xóa 10% batch
            evict_ids = [doc_id for doc_id, _ in paired[:evict_count]]

            await asyncio.to_thread(self._collection.delete, ids=evict_ids)
            logger.info(
                "[SemanticCache] LRU eviction | namespace=%s evicted=%d",
                namespace,
                len(evict_ids),
            )
        except Exception as exc:
            logger.warning("[SemanticCache] eviction error: %s", exc)

    async def _ttl_cleanup_loop(self) -> None:
        """
        Background task: mỗi 5 phút quét và xóa entries đã hết TTL.
        Tự cancel khi close() được gọi.
        """
        while True:
            try:
                await asyncio.sleep(300)  # 5 phút
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[SemanticCache] TTL cleanup error: %s", exc)

    async def _cleanup_expired(self) -> None:
        """Xóa tất cả entries đã hết TTL trong toàn bộ collection."""
        if not self._is_ready():
            return
        try:
            now = time.time()
            # Lấy tất cả entries có expires_at > 0
            results = self._collection.get(include=["metadatas"])
            ids = results.get("ids", [])
            metadatas = results.get("metadatas", [])

            expired_ids = [
                doc_id
                for doc_id, meta in zip(ids, metadatas)
                if float(meta.get("expires_at", 0)) > 0
                and float(meta.get("expires_at", 0)) < now
            ]

            if expired_ids:
                await asyncio.to_thread(self._collection.delete, ids=expired_ids)
                logger.info(
                    "[SemanticCache] TTL cleanup | removed=%d expired entries",
                    len(expired_ids),
                )
        except Exception as exc:
            logger.warning("[SemanticCache] _cleanup_expired error: %s", exc)

    def _record_hit(self, namespace: str) -> None:
        self._hit_counts[namespace] = self._hit_counts.get(namespace, 0) + 1

    def _record_miss(self, namespace: str) -> None:
        self._miss_counts[namespace] = self._miss_counts.get(namespace, 0) + 1
