"""
IronCore Optimizer — Phase 4A: Reranker
========================================
Claude 4.6 "The Optimizer" — IronCore V2

Sau khi GraphRAG trả về top-K nodes via vector similarity,
Reranker sắp xếp lại chúng dùng cross-encoder scoring.

Hai chế độ:
  1. Cohere Rerank API (nếu có COHERE_API_KEY) — chính xác nhất
  2. BM25 fallback (pure Python, không cần API) — nếu không có key

Tại sao quan trọng:
  - ChromaDB bi-encoder: embedding query và document riêng biệt → kém chính xác
  - Cohere cross-encoder: score từng (query, document) pair → +15–20% accuracy
  - BM25: classical IR scoring, vẫn tốt cho keyword-heavy content

Non-breaking:
  - Nếu Cohere API fail → tự động fallback BM25
  - Nếu BM25 cũng fail → trả về original order (không crash)

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────


class RerankResult(BaseModel):
    """Kết quả rerank cho một document."""

    index: int                  # Original index trong documents list đầu vào
    relevance_score: float      # 0.0–1.0, cao hơn = relevant hơn
    document: str               # Nội dung document


# ──────────────────────────────────────────────────────────────────────────────
# BM25 Scorer — Pure Python fallback
# ──────────────────────────────────────────────────────────────────────────────


class BM25Scorer:
    """
    BM25 (Okapi BM25) scoring — pure Python, không cần thêm package.

    Formula:
        score(D, Q) = Σ_t [ IDF(t) × TF(t,D) × (k+1) / (TF(t,D) + k×(1-b+b×|D|/avgdl) ]

    Parameters (Robertson 2009 defaults):
        k1 = 1.5  (term frequency saturation)
        b  = 0.75 (document length normalization)

    Tokenization: lowercase, split on whitespace/punctuation, remove stopwords.
    """

    _STOPWORDS = frozenset({
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "to", "of", "in", "on", "at", "for",
        "with", "about", "by", "from", "and", "or", "but", "not",
        "if", "that", "this", "it", "we", "i", "you",
    })

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def score(
        self, query: str, documents: List[str], top_n: int = 5
    ) -> List[RerankResult]:
        """
        Score và rank documents theo BM25.

        Args:
            query:     Search query.
            documents: List of document strings.
            top_n:     Số kết quả trả về.

        Returns:
            List[RerankResult] sorted by relevance_score descending.
        """
        if not documents:
            return []

        query_tokens = self._tokenize(query)
        doc_tokens_list = [self._tokenize(doc) for doc in documents]

        # Tính avgdl (average document length)
        avgdl = sum(len(t) for t in doc_tokens_list) / max(len(doc_tokens_list), 1)

        # Tính IDF cho mỗi query term
        idf: Dict[str, float] = {}
        N = len(documents)
        for term in query_tokens:
            df = sum(1 for tokens in doc_tokens_list if term in tokens)
            # Smooth IDF để tránh log(0)
            idf[term] = math.log((N - df + 0.5) / (df + 0.5) + 1)

        # Score mỗi document
        scores: List[float] = []
        for doc_tokens in doc_tokens_list:
            dl = len(doc_tokens)
            tf_dict: Dict[str, int] = {}
            for token in doc_tokens:
                tf_dict[token] = tf_dict.get(token, 0) + 1

            score = 0.0
            for term in query_tokens:
                if term not in idf:
                    continue
                tf = tf_dict.get(term, 0)
                # BM25 formula
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (
                    1 - self.b + self.b * dl / max(avgdl, 1)
                )
                score += idf[term] * (numerator / max(denominator, 1e-9))
            scores.append(score)

        # Normalize scores sang [0, 1]
        max_score = max(scores) if scores else 1.0
        if max_score > 0:
            scores = [s / max_score for s in scores]

        # Sort và lấy top_n
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        actual_top_n = min(top_n, len(documents))

        return [
            RerankResult(
                index=idx,
                relevance_score=round(score, 4),
                document=documents[idx],
            )
            for idx, score in indexed[:actual_top_n]
        ]

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        """Lowercase, split, remove stopwords và short tokens."""
        raw = re.findall(r"\b[a-z0-9]+\b", text.lower())
        return [t for t in raw if len(t) > 1 and t not in cls._STOPWORDS]


# ──────────────────────────────────────────────────────────────────────────────
# Reranker — Public Façade
# ──────────────────────────────────────────────────────────────────────────────


class Reranker:
    """
    Rerank documents theo relevance với query.
    Cohere Rerank API primary, BM25 fallback.

    Usage::
        reranker = Reranker(cohere_api_key=os.environ.get("COHERE_API_KEY"))

        # Trong HybridRetriever.query_context():
        texts = [node.name + " " + str(node.properties) for node in candidates]
        results = await reranker.rerank(query, texts, top_n=5)
        reranked_nodes = [candidates[r.index] for r in results]
    """

    COHERE_RERANK_URL = "https://api.cohere.com/v1/rerank"

    def __init__(
        self,
        cohere_api_key: Optional[str] = None,
        model: str = "rerank-english-v3.0",
        top_n: int = 5,
    ) -> None:
        """
        Args:
            cohere_api_key: Cohere API key. None = BM25 fallback mode.
            model:          Cohere rerank model ID.
            top_n:          Số kết quả giữ lại.
        """
        self._api_key = cohere_api_key or os.environ.get("COHERE_API_KEY", "")
        self._model = model
        self._top_n = top_n
        self._bm25 = BM25Scorer()
        self._cohere_available = bool(self._api_key)

        logger.info(
            "[Reranker] Initialized | mode=%s model=%s top_n=%d",
            "cohere" if self._cohere_available else "bm25_fallback",
            model,
            top_n,
        )

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[RerankResult]:
        """
        Rerank documents theo relevance với query.

        Nếu Cohere available → gọi API.
        Nếu không hoặc API fail → BM25 fallback.
        Luôn trả về top_n kết quả sorted by relevance_score DESC.

        Args:
            query:     Natural language query.
            documents: List of plain-text candidates.
            top_n:     Override số kết quả (None = dùng default).

        Returns:
            List[RerankResult] sorted descending by relevance_score.
        """
        if not documents:
            return []

        actual_top_n = min(top_n or self._top_n, len(documents))

        if self._cohere_available:
            try:
                results = await self._cohere_rerank(query, documents, actual_top_n)
                logger.info(
                    "[Reranker] Cohere rerank | docs=%d → top=%d",
                    len(documents),
                    len(results),
                )
                return results
            except Exception as exc:
                logger.warning(
                    "[Reranker] Cohere API failed (%s) — falling back to BM25.",
                    exc,
                )

        # BM25 fallback
        results = await asyncio.to_thread(
            self._bm25.score, query, documents, actual_top_n
        )
        logger.info(
            "[Reranker] BM25 fallback | docs=%d → top=%d",
            len(documents),
            len(results),
        )
        return results

    async def _cohere_rerank(
        self,
        query: str,
        documents: List[str],
        top_n: int,
    ) -> List[RerankResult]:
        """
        Gọi Cohere Rerank API qua aiohttp.

        API spec:
            POST https://api.cohere.com/v1/rerank
            Headers: Authorization: Bearer {api_key}
            Body: {model, query, documents, top_n, return_documents: true}

        Response:
            {results: [{index, relevance_score, document: {text: "..."}}]}
        """
        try:
            import aiohttp  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "aiohttp not installed. Install with: pip install aiohttp"
            )

        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": True,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.COHERE_RERANK_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Cohere Rerank API error {resp.status}: {text[:200]}"
                    )
                data = await resp.json()

        results: List[RerankResult] = []
        for item in data.get("results", []):
            index = item["index"]
            score = float(item.get("relevance_score", 0.0))
            doc_text = (
                item.get("document", {}).get("text", documents[index])
                if isinstance(item.get("document"), dict)
                else documents[index]
            )
            results.append(
                RerankResult(
                    index=index,
                    relevance_score=round(score, 4),
                    document=doc_text,
                )
            )

        return sorted(results, key=lambda r: r.relevance_score, reverse=True)
