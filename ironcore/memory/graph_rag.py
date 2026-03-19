"""
IronCore: GraphRAG Memory Engine — Phase 2
==========================================
Hybrid Graph + Vector Store for intelligent agent memory.

Architecture:
  - VectorStore  : ChromaDB with local SentenceTransformer embeddings
  - GraphStore   : NetworkX in-memory directional knowledge graph
  - HybridRetriever: Vector search → Graph BFS expansion → scored RAGContext
  - GraphRAGMemory : Public façade (replaces stub from previous session)

Dependencies:
    pip install chromadb networkx sentence-transformers

NOTE: Entity extraction is handled by a lightweight heuristic in this phase.
      It will be upgraded to HybridEntityExtractor when Phase 3 lands.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class GraphRAGError(Exception):
    """Base exception for all GraphRAG errors."""


class VectorStoreError(GraphRAGError):
    """Raised on ChromaDB failures."""


class GraphStoreError(GraphRAGError):
    """Raised on NetworkX graph failures."""


# ---------------------------------------------------------------------------
# Data Models (Pydantic V2)
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel, Field

    class KnowledgeNode(BaseModel):
        """A single entity node in the knowledge graph."""

        id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        entity_type: str  # "person", "concept", "action", "system", "tech"
        name: str
        properties: Dict[str, Any] = Field(default_factory=dict)
        embedding: Optional[List[float]] = None
        created_at: float = Field(default_factory=time.time)
        last_accessed: float = Field(default_factory=time.time)
        access_count: int = 0

    class KnowledgeEdge(BaseModel):
        """A typed directed relationship between two nodes."""

        id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        source_id: str
        target_id: str
        relationship: str  # "uses", "causes", "is_part_of", "depends_on", "discusses"
        weight: float = 1.0
        properties: Dict[str, Any] = Field(default_factory=dict)

    class ScoredNode(BaseModel):
        """A node paired with its retrieval relevance score."""

        node: KnowledgeNode
        score: float

    class RAGContext(BaseModel):
        """The retrieved context payload returned to the LLM."""

        nodes: List[KnowledgeNode]
        edges: List[KnowledgeEdge]
        relevance_scores: Dict[str, float]
        query_embedding: List[float]
        retrieval_time_ms: float

except ImportError as _pydantic_missing:
    raise ImportError(
        "Pydantic V2 is required. Install with: pip install pydantic>=2.0"
    ) from _pydantic_missing


# ---------------------------------------------------------------------------
# VectorStore — ChromaDB wrapper
# ---------------------------------------------------------------------------

class VectorStore:
    """
    Wraps ChromaDB for semantic similarity search over KnowledgeNodes.

    Uses all-MiniLM-L6-v2 SentenceTransformer embeddings (local, no API key
    required). Falls back to ChromaDB's default embedding if sentence-transformers
    is unavailable.
    """

    def __init__(self, persist_directory: str = ".ironcore/chroma") -> None:
        self._persist_dir = persist_directory
        self._client: Any = None
        self._collection: Any = None
        self._embedding_fn: Any = None
        self._initialized = False

    async def initialize(self) -> None:
        """Lazy-initialize ChromaDB client and embedding function (async-safe)."""
        await asyncio.to_thread(self._sync_init)
        self._initialized = True
        logger.info("[VectorStore] ChromaDB initialized. persist_dir=%s", self._persist_dir)

    def _sync_init(self) -> None:
        try:
            import chromadb
            from chromadb.utils import embedding_functions  # type: ignore[import]

            self._client = chromadb.PersistentClient(path=self._persist_dir)
            try:
                self._embedding_fn = (
                    embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name="all-MiniLM-L6-v2"
                    )
                )
            except Exception:
                logger.warning(
                    "[VectorStore] SentenceTransformer unavailable; using ChromaDB default."
                )
                self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()  # type: ignore[attr-defined]

            self._collection = self._client.get_or_create_collection(
                name="ironcore_knowledge",
                embedding_function=self._embedding_fn,
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError as exc:
            raise VectorStoreError(
                "ChromaDB not installed. Run: pip install chromadb"
            ) from exc

    def _assert_ready(self) -> None:
        if not self._initialized or self._collection is None:
            raise VectorStoreError(
                "VectorStore not initialized. Await initialize() before use."
            )

    async def add(self, node: KnowledgeNode, text: str) -> None:
        """Embed `text` and store it as a ChromaDB document linked to `node`."""
        self._assert_ready()
        await asyncio.to_thread(
            self._collection.upsert,
            ids=[node.id],
            documents=[text],
            metadatas=[
                {
                    "entity_type": node.entity_type,
                    "name": node.name,
                    "created_at": node.created_at,
                }
            ],
        )
        logger.debug("[VectorStore] Stored node id=%s name=%s", node.id, node.name)

    async def search(self, query: str, top_k: int = 10) -> List[ScoredNode]:
        """Return up to `top_k` nodes ranked by cosine similarity to `query`."""
        self._assert_ready()
        n_results = min(top_k, max(1, await self._count()))
        results = await asyncio.to_thread(
            self._collection.query,
            query_texts=[query],
            n_results=n_results,
        )

        scored: List[ScoredNode] = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for node_id, distance, meta in zip(ids, distances, metadatas):
            score = max(0.0, 1.0 - float(distance))  # cosine distance → similarity
            node = KnowledgeNode(
                id=node_id,
                entity_type=meta.get("entity_type", "concept"),
                name=meta.get("name", ""),
                created_at=float(meta.get("created_at", time.time())),
            )
            scored.append(ScoredNode(node=node, score=score))

        logger.debug(
            "[VectorStore] Search: %d results for query='%s'", len(scored), query[:50]
        )
        return scored

    async def delete(self, node_id: str) -> None:
        """Remove a node from the vector store (GDPR erasure)."""
        self._assert_ready()
        await asyncio.to_thread(self._collection.delete, ids=[node_id])
        logger.debug("[VectorStore] Deleted node id=%s", node_id)

    async def get_embedding(self, text: str) -> List[float]:
        """Return the raw embedding vector for `text`."""
        self._assert_ready()
        if self._embedding_fn is None:
            raise VectorStoreError("Embedding function not available.")
        embeddings = await asyncio.to_thread(self._embedding_fn, [text])
        return list(embeddings[0])

    async def _count(self) -> int:
        if self._collection is None:
            return 0
        return await asyncio.to_thread(self._collection.count)


# ---------------------------------------------------------------------------
# GraphStore — NetworkX in-memory knowledge graph
# ---------------------------------------------------------------------------

class GraphStore:
    """
    In-memory directed knowledge graph backed by NetworkX.

    Nodes are KnowledgeNode entities.
    Edges are typed KnowledgeEdge relationships.
    """

    def __init__(self) -> None:
        try:
            import networkx as nx  # type: ignore[import]
            self._nx = nx
        except ImportError as exc:
            raise GraphStoreError(
                "NetworkX not installed. Run: pip install networkx"
            ) from exc

        self._graph: Any = self._nx.DiGraph()
        self._nodes: Dict[str, KnowledgeNode] = {}
        self._edges: Dict[str, KnowledgeEdge] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_node(self, node: KnowledgeNode) -> None:
        """Insert or merge a knowledge node into the graph."""
        if node.id in self._nodes:
            existing = self._nodes[node.id]
            existing.properties.update(node.properties)
            existing.access_count += 1
            existing.last_accessed = time.time()
        else:
            self._nodes[node.id] = node
            self._graph.add_node(
                node.id,
                entity_type=node.entity_type,
                name=node.name,
            )
        logger.debug("[GraphStore] Node upserted: id=%s name=%s", node.id, node.name)

    def add_edge(self, edge: KnowledgeEdge) -> None:
        """Insert a directed edge. Silently skips if either endpoint is missing."""
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            logger.warning(
                "[GraphStore] Skipping edge — unknown node(s): src=%s tgt=%s",
                edge.source_id,
                edge.target_id,
            )
            return
        self._edges[edge.id] = edge
        self._graph.add_edge(
            edge.source_id,
            edge.target_id,
            relationship=edge.relationship,
            weight=edge.weight,
            edge_id=edge.id,
        )
        logger.debug(
            "[GraphStore] Edge: %s -[%s]-> %s",
            edge.source_id,
            edge.relationship,
            edge.target_id,
        )

    def remove_node(self, node_id: str) -> None:
        """Delete a node and reap all its incident edges."""
        if node_id in self._graph:
            self._graph.remove_node(node_id)
        self._nodes.pop(node_id, None)
        self._edges = {
            eid: e
            for eid, e in self._edges.items()
            if e.source_id != node_id and e.target_id != node_id
        }
        logger.debug("[GraphStore] Removed node id=%s", node_id)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_neighbors(self, node_id: str, depth: int = 2) -> List[KnowledgeNode]:
        """
        BFS up to `depth` hops from `node_id`.

        Traverses both outgoing and incoming edges so the neighborhood
        is undirected in practice.
        """
        if node_id not in self._graph:
            return []

        visited: set = set()
        queue: List[Tuple[str, int]] = [(node_id, 0)]
        result: List[KnowledgeNode] = []

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_id in visited or current_depth > depth:
                continue
            visited.add(current_id)

            if current_id != node_id and current_id in self._nodes:
                result.append(self._nodes[current_id])

            if current_depth < depth:
                successors = list(self._graph.successors(current_id))
                predecessors = list(self._graph.predecessors(current_id))
                for neighbor in successors + predecessors:
                    if neighbor not in visited:
                        queue.append((neighbor, current_depth + 1))

        return result

    def find_path(self, source_id: str, target_id: str) -> List[str]:
        """Return shortest node-ID path between two nodes, or [] if unreachable."""
        try:
            return list(
                self._nx.shortest_path(self._graph, source=source_id, target=target_id)
            )
        except (self._nx.NetworkXNoPath, self._nx.NodeNotFound):
            return []

    def get_community(self, node_id: str) -> List[KnowledgeNode]:
        """
        Return the 20 highest-PageRank nodes in the connected component
        containing `node_id`. Used for community-level context injection.
        """
        if node_id not in self._graph or len(self._graph.nodes) < 2:
            return list(self._nodes.values())[:10]

        undirected = self._graph.to_undirected()
        try:
            pagerank = self._nx.pagerank(undirected, max_iter=100, tol=1.0e-4)
        except self._nx.PowerIterationFailedConvergence:
            pagerank = {n: 1.0 / len(self._graph.nodes) for n in self._graph.nodes}

        if self._nx.is_connected(undirected):
            component = set(undirected.nodes())
        else:
            component = self._nx.node_connected_component(undirected, node_id)

        ordered = sorted(
            [(n, pagerank.get(n, 0.0)) for n in component if n != node_id],
            key=lambda x: x[1],
            reverse=True,
        )
        return [self._nodes[n] for n, _ in ordered[:20] if n in self._nodes]

    def get_edges_for_nodes(self, node_ids: set) -> List[KnowledgeEdge]:
        """Return edges where BOTH endpoints are in `node_ids`."""
        return [
            e
            for e in self._edges.values()
            if e.source_id in node_ids and e.target_id in node_ids
        ]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)


# ---------------------------------------------------------------------------
# HybridRetriever — vector search + graph traversal
# ---------------------------------------------------------------------------

class HybridRetriever:
    """
    Combines VectorStore similarity search with GraphStore BFS expansion.

    Query pipeline:
        1. Embed query → top-K vector candidates
        2. BFS-expand each candidate via GraphStore (depth=2)
        3. Rank all collected nodes by score (graph-expanded: ×0.5 decay)
        4. [Optional] Rerank top candidates via Cohere/BM25 (Phase 4)
        5. Trim to max_tokens budget (≈ 100 tokens per node)
        6. Collect cross-node edges → assemble RAGContext
    """

    def __init__(
        self,
        vector_store: VectorStore,
        graph_store: GraphStore,
        reranker: Optional[Any] = None,    # V2 Phase 4: Reranker | None
    ) -> None:
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._reranker = reranker           # Optional Reranker (Phase 4)

    async def query_context(
        self,
        query: str,
        top_k_vector: int = 10,
        graph_depth: int = 2,
        max_tokens: int = 4000,
    ) -> RAGContext:
        """
        Run hybrid retrieval and return a scored RAGContext.

        Args:
            query:          Natural language search query.
            top_k_vector:   Vector-search candidate count.
            graph_depth:    BFS expansion depth from each candidate.
            max_tokens:     Approximate context token budget.

        Returns:
            RAGContext with ranked nodes, connecting edges, and scores.
        """
        start_time = time.time()

        # Step 1 — vector similarity candidates
        scored_candidates = await self._vector_store.search(query, top_k=top_k_vector)
        query_embedding = await self._vector_store.get_embedding(query)

        # Step 2 — graph expansion
        all_nodes: Dict[str, KnowledgeNode] = {}
        relevance_scores: Dict[str, float] = {}

        for scored in scored_candidates:
            node = scored.node
            all_nodes[node.id] = node
            relevance_scores[node.id] = scored.score

            for neighbor in self._graph_store.get_neighbors(node.id, depth=graph_depth):
                if neighbor.id not in all_nodes:
                    all_nodes[neighbor.id] = neighbor
                    relevance_scores[neighbor.id] = scored.score * 0.5

        # Step 3 — rank by descending score
        ranked_ids = sorted(
            relevance_scores, key=lambda nid: relevance_scores[nid], reverse=True
        )

        # ── V2 Phase 4: Reranker — re-score top candidates via cross-encoder ──
        if self._reranker is not None and len(ranked_ids) > 1:
            try:
                # Lấy top-20 candidates để rerank (giới hạn chi phí rerank)
                candidates_for_rerank = ranked_ids[:20]
                texts = [
                    all_nodes[nid].name + " " + str(all_nodes[nid].properties)
                    for nid in candidates_for_rerank
                    if nid in all_nodes
                ]
                rerank_results = await self._reranker.rerank(
                    query, texts, top_n=len(candidates_for_rerank)
                )
                # Cập nhật relevance_scores với reranker scores
                for result in rerank_results:
                    if result.index < len(candidates_for_rerank):
                        nid = candidates_for_rerank[result.index]
                        relevance_scores[nid] = result.relevance_score
                # Re-sort sau khi rerank
                ranked_ids = sorted(
                    relevance_scores, key=lambda nid: relevance_scores[nid], reverse=True
                )
                logger.info(
                    "[HybridRetriever] Reranked %d candidates.",
                    len(candidates_for_rerank),
                )
            except Exception as _rerank_exc:
                logger.warning(
                    "[HybridRetriever] Reranker failed (non-fatal): %s",
                    _rerank_exc,
                )
        # ──────────────────────────────────────────────────────────

        # Step 4 (was Step 4) — trim to token budget (~100 tokens per node)
        max_nodes = max(1, max_tokens // 100)
        trimmed_ids = ranked_ids[:max_nodes]
        trimmed_nodes = [all_nodes[nid] for nid in trimmed_ids if nid in all_nodes]
        trimmed_scores = {nid: relevance_scores[nid] for nid in trimmed_ids}

        # Step 5 — edges between selected nodes
        edges = self._graph_store.get_edges_for_nodes(set(trimmed_ids))

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "[HybridRetriever] nodes=%d edges=%d time_ms=%.1f query='%s'",
            len(trimmed_nodes),
            len(edges),
            elapsed_ms,
            query[:60],
        )
        return RAGContext(
            nodes=trimmed_nodes,
            edges=edges,
            relevance_scores=trimmed_scores,
            query_embedding=query_embedding,
            retrieval_time_ms=elapsed_ms,
        )


# ---------------------------------------------------------------------------
# Lightweight heuristic entity extractor (Phase 3 upgrades this)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "to", "of", "in", "on", "at", "for", "with", "about", "by", "from",
        "and", "or", "but", "not", "if", "that", "this", "it", "we", "i",
        "you", "he", "she", "they", "them", "its", "our", "your", "their",
    }
)

_TECH_KEYWORDS = frozenset(
    {
        "python", "docker", "neo4j", "chromadb", "networkx", "llm", "api",
        "ironcore", "playwright", "sqlite", "asyncio", "pydantic", "fastapi",
        "redis", "kafka", "postgres", "mongodb", "openai", "anthropic",
    }
)


def _extract_simple_entities(text: str) -> List[Tuple[str, str]]:
    """
    Lightweight heuristic NER — no LLM call, no spaCy.

    Returns list of (name, entity_type) tuples.
    NOTE: Replaced by HybridEntityExtractor (Phase 3).
    """
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9_\-\.]*\b", text)
    entities: List[Tuple[str, str]] = []
    seen: set = set()

    for word in words:
        lower = word.lower()
        if lower in _STOP_WORDS or len(word) < 3 or lower in seen:
            continue
        if word[0].isupper() or lower in _TECH_KEYWORDS:
            seen.add(lower)
            entity_type = "tech" if lower in _TECH_KEYWORDS else "concept"
            entities.append((word, entity_type))

    for match in re.finditer(r"\bsession[_\-]?\w+\b", text, re.IGNORECASE):
        val = match.group(0)
        if val.lower() not in seen:
            seen.add(val.lower())
            entities.append((val, "action"))

    return entities[:15]  # cap to avoid explosion on long texts


def _stable_id(name: str) -> str:
    """
    Deterministic, UUID-shaped ID derived from an entity name.

    Using content-hash IDs means adding the same entity twice produces
    the same node ID — GraphStore.add_node() merges instead of duplicating.
    """
    digest = hashlib.sha256(name.lower().encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


# ---------------------------------------------------------------------------
# GraphRAGMemory — public interface
# ---------------------------------------------------------------------------

class GraphRAGMemory:
    """
    IronCore's hybrid memory system — public façade for The Brain.

    Replaces the stub from the previous session with a full production
    implementation of VectorStore + GraphStore + HybridRetriever.

    Phase 3 upgrade: accepts an optional ``entity_extractor`` (HybridEntityExtractor)
    to replace the lightweight heuristic with accurate LLM-backed triple extraction.

    Quick start (Phase 3 with extractor)::

        from ironcore.core.entity_extractor import HybridEntityExtractor
        extractor = await HybridEntityExtractor.create()
        memory = await GraphRAGMemory.create(entity_extractor=extractor)
        await memory.add_interaction(prompt, response, metadata)
        ctx = await memory.query_context("What did the user ask about Docker?")
    """

    def __init__(
        self,
        vector_store: VectorStore,
        graph_store: GraphStore,
        retriever: HybridRetriever,
        entity_extractor: Optional[Any] = None,
    ) -> None:
        self._vector_store = vector_store
        self._graph_store = graph_store
        self._retriever = retriever
        self._entity_extractor = entity_extractor  # HybridEntityExtractor | None
        # Legacy heuristic cache (used when entity_extractor is None)
        self._extraction_cache: Dict[str, List[Tuple[str, str]]] = {}

    @classmethod
    async def create(
        cls,
        persist_directory: str = ".ironcore/chroma",
        entity_extractor: Optional[Any] = None,
    ) -> "GraphRAGMemory":
        """
        Factory: initialize all sub-components and return a ready instance.

        Args:
            persist_directory: Path for ChromaDB persistence.
            entity_extractor:  Optional HybridEntityExtractor from Phase 3.
                               When supplied, entity + triple extraction is
                               powered by LLM/spaCy instead of the lightweight
                               heuristic. Pass ``None`` to keep Phase 2 behaviour.
        """
        vector_store = VectorStore(persist_directory=persist_directory)
        await vector_store.initialize()
        graph_store = GraphStore()
        retriever = HybridRetriever(vector_store, graph_store)
        instance = cls(vector_store, graph_store, retriever, entity_extractor)
        logger.info(
            "[GraphRAGMemory] Ready. persist_dir=%s | extractor=%s",
            persist_directory,
            type(entity_extractor).__name__ if entity_extractor is not None else "heuristic",
        )
        return instance

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def add_interaction(
        self,
        prompt: str,
        response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Extract entities / triples from prompt+response and persist in memory.

        Phase 3 behaviour (entity_extractor supplied):
          - Delegates to HybridEntityExtractor.extract() for accurate NLP.
          - Creates KnowledgeNode per EntitySpan.
          - Creates typed KnowledgeEdge per Triple  (subject→predicate→object).

        Phase 2 fallback (no extractor):
          - Uses lightweight _extract_simple_entities() heuristic.
          - Creates KnowledgeNode per entity + co-occurrence edges only.

        Args:
            prompt:   User/agent prompt text.
            response: LLM/tool response text.
            metadata: Optional extra properties stored on every node.
        """
        metadata = metadata or {}
        combined_text = f"{prompt}\n{response}"
        text_hash = hashlib.md5(combined_text.encode()).hexdigest()

        created_nodes: List[KnowledgeNode] = []

        # ── Phase 3: HybridEntityExtractor path ─────────────────────────────
        if self._entity_extractor is not None:
            try:
                extraction = await self._entity_extractor.extract(combined_text)

                # Entity nodes
                for span in extraction.entities:
                    node = KnowledgeNode(
                        id=_stable_id(span.text),
                        entity_type=span.entity_type.lower(),
                        name=span.text,
                        properties={
                            **metadata,
                            "source_prompt": prompt[:200],
                            "confidence": span.confidence,
                        },
                    )
                    self._graph_store.add_node(node)
                    await self._vector_store.add(
                        node, text=f"{span.text} {prompt[:100]}"
                    )
                    created_nodes.append(node)

                # Triple edges  (subject -[predicate]-> object)
                for triple in extraction.triples:
                    self._graph_store.add_edge(
                        KnowledgeEdge(
                            source_id=_stable_id(triple.subject),
                            target_id=_stable_id(triple.object),
                            relationship=triple.predicate,
                            weight=triple.confidence,
                            properties={"source_text": triple.source_text[:200]},
                        )
                    )

                logger.info(
                    "[GraphRAGMemory] Phase3 extraction: "
                    "%d entities, %d triples | model=%s",
                    len(extraction.entities),
                    len(extraction.triples),
                    extraction.model_used,
                )
            except Exception as exc:
                # Extractor failed — degrade gracefully to heuristic
                logger.warning(
                    "[GraphRAGMemory] HybridEntityExtractor failed, "
                    "falling back to heuristic: %s",
                    exc,
                )
                self._entity_extractor = None
                return await self.add_interaction(prompt, response, metadata)

        # ── Phase 2 fallback: lightweight heuristic ──────────────────────────
        else:
            if text_hash not in self._extraction_cache:
                self._extraction_cache[text_hash] = _extract_simple_entities(
                    combined_text
                )
            entities = self._extraction_cache[text_hash]

            for entity_name, entity_type in entities:
                node = KnowledgeNode(
                    id=_stable_id(entity_name),
                    entity_type=entity_type,
                    name=entity_name,
                    properties={**metadata, "source_prompt": prompt[:200]},
                )
                self._graph_store.add_node(node)
                await self._vector_store.add(
                    node, text=f"{entity_name} {prompt[:100]}"
                )
                created_nodes.append(node)

            # Co-occurrence edges (heuristic path only)
            for i, node_a in enumerate(created_nodes):
                for node_b in created_nodes[i + 1 :]:
                    self._graph_store.add_edge(
                        KnowledgeEdge(
                            source_id=node_a.id,
                            target_id=node_b.id,
                            relationship="co_occurs_with",
                            weight=0.5,
                        )
                    )

        # ── Shared: interaction anchor node + discusses edges ─────────────────
        interaction_node = KnowledgeNode(
            id=str(uuid.uuid4()),
            entity_type="action",
            name=f"interaction:{text_hash[:8]}",
            properties={
                **metadata,
                "prompt_preview": prompt[:200],
                "response_preview": response[:200],
                "timestamp": time.time(),
            },
        )
        self._graph_store.add_node(interaction_node)
        await self._vector_store.add(interaction_node, text=combined_text[:500])

        for entity_node in created_nodes:
            self._graph_store.add_edge(
                KnowledgeEdge(
                    source_id=interaction_node.id,
                    target_id=entity_node.id,
                    relationship="discusses",
                )
            )

        logger.info(
            "[GraphRAGMemory] Interaction stored: %d entities | nodes=%d edges=%d",
            len(created_nodes),
            self._graph_store.node_count,
            self._graph_store.edge_count,
        )

    async def query_context(
        self,
        query: str,
        max_tokens: int = 4000,
    ) -> RAGContext:
        """
        Retrieve relevant context for `query` via hybrid search.

        Args:
            query:      Natural language query.
            max_tokens: Approximate token budget for the returned context.

        Returns:
            RAGContext with ranked nodes, edges, and relevance scores.
        """
        return await self._retriever.query_context(query, max_tokens=max_tokens)

    async def forget(self, node_id: str) -> None:
        """
        Erase a node from both stores — supports GDPR right-to-erasure.

        Args:
            node_id: UUID of the KnowledgeNode to permanently delete.
        """
        self._graph_store.remove_node(node_id)
        try:
            await self._vector_store.delete(node_id)
        except VectorStoreError:
            pass  # node may not be in vector store; that's fine
        logger.info("[GraphRAGMemory] Forgot node id=%s", node_id)

    async def consolidate(self) -> None:
        """
        Merge duplicate entities (same name, multiple IDs) and prune
        stale nodes (never accessed, older than 7 days).

        Call periodically to keep the graph lean.
        """
        # --- find duplicates by normalized name ---
        name_to_nodes: Dict[str, List[KnowledgeNode]] = {}
        for node in list(self._graph_store._nodes.values()):
            name_to_nodes.setdefault(node.name.lower(), []).append(node)

        merged_count = 0
        for _name, duplicates in name_to_nodes.items():
            if len(duplicates) <= 1:
                continue
            # Keep the node with the most incident edges
            primary = max(
                duplicates,
                key=lambda n: self._graph_store._graph.degree(n.id)
                if n.id in self._graph_store._graph
                else 0,
            )
            for duplicate in duplicates:
                if duplicate.id == primary.id:
                    continue
                # Rewire all edges that pointed to the duplicate → primary
                for edge in list(self._graph_store._edges.values()):
                    if edge.source_id == duplicate.id:
                        self._graph_store.add_edge(
                            KnowledgeEdge(
                                source_id=primary.id,
                                target_id=edge.target_id,
                                relationship=edge.relationship,
                                weight=edge.weight,
                            )
                        )
                    elif edge.target_id == duplicate.id:
                        self._graph_store.add_edge(
                            KnowledgeEdge(
                                source_id=edge.source_id,
                                target_id=primary.id,
                                relationship=edge.relationship,
                                weight=edge.weight,
                            )
                        )
                await self.forget(duplicate.id)
                merged_count += 1

        # --- prune stale nodes (never accessed, > 7 days old) ---
        cutoff = time.time() - 7 * 24 * 3600
        pruned_count = 0
        for node in list(self._graph_store._nodes.values()):
            if node.access_count == 0 and node.created_at < cutoff:
                await self.forget(node.id)
                pruned_count += 1

        logger.info(
            "[GraphRAGMemory] Consolidation: merged=%d pruned=%d "
            "remaining_nodes=%d remaining_edges=%d",
            merged_count,
            pruned_count,
            self._graph_store.node_count,
            self._graph_store.edge_count,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, int]:
        """Quick stats snapshot for monitoring dashboards."""
        return {
            "node_count": self._graph_store.node_count,
            "edge_count": self._graph_store.edge_count,
        }
