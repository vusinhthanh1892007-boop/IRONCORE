"""
IronCore: Entity Extractor — NLP Pipeline with Triple Extraction
================================================================
Phase 3 — The Brain (Claude Sonnet 4.6)

Responsibilities:
  - FastEntityExtractor   : spaCy NER for high-throughput entity detection
                            (regex heuristic fallback if spaCy unavailable)
  - LLMEntityExtractor    : LLM-based Subject-Predicate-Object triple extraction
                            with JSON schema validation + retry + batch processing
  - HybridEntityExtractor : Routes between fast / LLM based on text complexity
                            with content-hash caching

Triple format  :  (Subject) -[Predicate]-> (Object)
Example        :  "IronCore uses Docker for sandbox isolation"
  → Triple(subject="IronCore", predicate="uses",     object="Docker",    ...)
  → Triple(subject="Docker",   predicate="provides", object="isolation", ...)

Integration with Phase 2 (GraphRAGMemory):
  - GraphRAGMemory.add_interaction() delegates to HybridEntityExtractor.
  - Each EntitySpan  → KnowledgeNode
  - Each Triple      → KnowledgeEdge (source=subject, target=object, rel=predicate)

Dependencies:
    pip install spacy litellm pydantic>=2.0
    python -m spacy download en_core_web_sm

Author: The Brain (IronCore Project)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────

class ExtractorError(Exception):
    """Base exception for all Entity Extractor errors."""


class LLMExtractionError(ExtractorError):
    """Raised when LLM triple-extraction fails after all retries."""


class SpaCyUnavailableError(ExtractorError):
    """Raised when spaCy or its NLP model is not installed."""


# ──────────────────────────────────────────────────────────────────────────────
# Data Models (Pydantic V2)
# ──────────────────────────────────────────────────────────────────────────────

class EntitySpan(BaseModel):
    """A single named entity detected in the source text."""

    text: str
    entity_type: str          # PERSON | ORG | TECH | CONCEPT | ACTION | LOCATION
    start: int                # character start offset in source text
    end: int                  # character end offset (exclusive)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Triple(BaseModel):
    """
    An explicitly typed Subject-Predicate-Object relationship.

    Designed to map directly to a KnowledgeEdge in GraphRAGMemory.
    """

    subject: str
    predicate: str            # e.g. "uses", "depends_on", "provides", "is_part_of"
    object: str
    subject_type: str         # EntitySpan.entity_type for the subject
    object_type: str          # EntitySpan.entity_type for the object
    source_text: str          # the original sentence / snippet the triple was extracted from
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Complete output of one extraction run — entities + triples."""

    entities: List[EntitySpan]
    triples: List[Triple]
    processing_time_ms: float
    model_used: str           # "spacy:en_core_web_sm" | "llm:claude-haiku-3-5" | "regex_fallback" …


# ──────────────────────────────────────────────────────────────────────────────
# Canonical Entity Type Constants
# ──────────────────────────────────────────────────────────────────────────────

_VALID_ENTITY_TYPES = frozenset({"PERSON", "ORG", "TECH", "CONCEPT", "ACTION", "LOCATION"})

# Mapping from spaCy's built-in labels → IronCore canonical types
_SPACY_TYPE_MAP: Dict[str, str] = {
    "PERSON":       "PERSON",
    "ORG":          "ORG",
    "GPE":          "LOCATION",
    "LOC":          "LOCATION",
    "FAC":          "LOCATION",
    "PRODUCT":      "TECH",
    "WORK_OF_ART":  "CONCEPT",
    "LAW":          "CONCEPT",
    "LANGUAGE":     "TECH",
    "DATE":         "CONCEPT",
    "TIME":         "CONCEPT",
    "EVENT":        "CONCEPT",
    "NORP":         "ORG",
    "MONEY":        "CONCEPT",
    "CARDINAL":     "CONCEPT",
    "ORDINAL":      "CONCEPT",
    "QUANTITY":     "CONCEPT",
    "PERCENT":      "CONCEPT",
}

# Known technology / infrastructure keywords that spaCy NER often misses
_TECH_TERMS: frozenset = frozenset({
    "python", "docker", "neo4j", "chromadb", "networkx", "llm", "api",
    "ironcore", "playwright", "sqlite", "asyncio", "pydantic", "fastapi",
    "redis", "kafka", "postgres", "mongodb", "openai", "anthropic",
    "spacy", "litellm", "gvisor", "nginx", "kubernetes", "git", "github",
    "linux", "ubuntu", "bash", "json", "http", "https", "rest", "graphql",
    "langchain", "llamaindex", "ollama", "llava", "gpt", "claude", "gemini",
    "huggingface", "transformers", "pytorch", "tensorflow", "react", "nodejs",
    "typescript", "javascript", "rust", "golang", "java", "csharp", "dotnet",
    "aws", "gcp", "azure", "terraform", "ansible", "helm", "argocd",
    "elasticsearch", "kibana", "prometheus", "grafana", "celery", "rabbitmq",
    "websocket", "grpc", "protobuf", "oauth", "jwt", "tls", "ssl",
})


# ──────────────────────────────────────────────────────────────────────────────
# FastEntityExtractor — spaCy NER (no LLM call, no network)
# ──────────────────────────────────────────────────────────────────────────────

class FastEntityExtractor:
    """
    High-throughput named-entity extractor using spaCy.

    - Zero LLM calls — fully local inference.
    - Extracts EntitySpan objects only (no triples).
    - Falls back to regex heuristics transparently if spaCy is absent.

    Usage::

        extractor = FastEntityExtractor()
        await extractor.initialize()
        result = await extractor.extract("IronCore uses Docker.")
    """

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        self._model_name = model_name
        self._nlp: Any = None
        self._spacy_available = False

    async def initialize(self) -> None:
        """Load spaCy NLP model in a thread pool (non-blocking)."""
        await asyncio.to_thread(self._sync_load)

    def _sync_load(self) -> None:
        try:
            import spacy  # type: ignore[import]
        except ImportError:
            self._spacy_available = False
            logger.warning(
                "[FastExtractor] spaCy not installed. Using regex fallback. "
                "Install with: pip install spacy && python -m spacy download %s",
                self._model_name,
            )
            return

        for model in (self._model_name, "en_core_web_trf", "en_core_web_md"):
            try:
                self._nlp = spacy.load(model)
                self._spacy_available = True
                logger.info("[FastExtractor] Loaded spaCy model: %s", model)
                return
            except OSError:
                continue

        self._spacy_available = False
        logger.warning(
            "[FastExtractor] Could not load any spaCy model. Falling back to regex. "
            "Run: python -m spacy download %s",
            self._model_name,
        )

    async def extract(self, text: str) -> ExtractionResult:
        """
        Extract named entities from `text`.

        Returns ExtractionResult with ``entities`` populated and ``triples=[]``.
        Falls back to regex heuristics if spaCy is unavailable.
        """
        start_time = time.time()

        if self._spacy_available and self._nlp is not None:
            entities = await asyncio.to_thread(self._spacy_extract, text)
            model_used = f"spacy:{self._model_name}"
        else:
            entities = self._regex_fallback(text)
            model_used = "regex_fallback"

        elapsed_ms = (time.time() - start_time) * 1_000
        logger.debug(
            "[FastExtractor] %d entities in %.1fms | model=%s",
            len(entities), elapsed_ms, model_used,
        )
        return ExtractionResult(
            entities=entities,
            triples=[],
            processing_time_ms=elapsed_ms,
            model_used=model_used,
        )

    # ── spaCy path ────────────────────────────────────────────────────────────

    def _spacy_extract(self, text: str) -> List[EntitySpan]:
        """Synchronous spaCy NER pass — called via asyncio.to_thread."""
        doc = self._nlp(text)
        spans: List[EntitySpan] = []
        seen: set = set()

        for ent in doc.ents:
            key = ent.text.lower().strip()
            if key in seen or len(key) < 2:
                continue
            seen.add(key)
            entity_type = _SPACY_TYPE_MAP.get(ent.label_, "CONCEPT")
            if key in _TECH_TERMS:
                entity_type = "TECH"
            spans.append(EntitySpan(
                text=ent.text,
                entity_type=entity_type,
                start=ent.start_char,
                end=ent.end_char,
                confidence=0.90,
            ))

        # Supplement NER with known TECH terms that spaCy often misses
        for term in _TECH_TERMS:
            for match in re.finditer(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE):
                key = match.group(0).lower()
                if key not in seen:
                    seen.add(key)
                    spans.append(EntitySpan(
                        text=match.group(0),
                        entity_type="TECH",
                        start=match.start(),
                        end=match.end(),
                        confidence=0.80,
                    ))

        return spans[:40]

    # ── Regex fallback path ───────────────────────────────────────────────────

    def _regex_fallback(self, text: str) -> List[EntitySpan]:
        """
        Heuristic NER without spaCy:
          1. Capitalized proper nouns / CamelCase tokens → CONCEPT or TECH
          2. Known tech keywords → TECH
        """
        spans: List[EntitySpan] = []
        seen: set = set()

        for match in re.finditer(r"\b[A-Z][a-zA-Z0-9\-_]{2,}\b", text):
            word = match.group(0)
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            entity_type = "TECH" if key in _TECH_TERMS else "CONCEPT"
            spans.append(EntitySpan(
                text=word,
                entity_type=entity_type,
                start=match.start(),
                end=match.end(),
                confidence=0.60,
            ))

        for term in _TECH_TERMS:
            for match in re.finditer(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE):
                key = match.group(0).lower()
                if key not in seen:
                    seen.add(key)
                    spans.append(EntitySpan(
                        text=match.group(0),
                        entity_type="TECH",
                        start=match.start(),
                        end=match.end(),
                        confidence=0.75,
                    ))

        return spans[:40]


# ──────────────────────────────────────────────────────────────────────────────
# LLM Extraction Prompt
# ──────────────────────────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM_PROMPT = """You are an expert Knowledge Graph builder.
Extract ALL meaningful Subject-Predicate-Object relationships from the provided text.

Rules:
1. Keep subjects and objects concise (1–4 words).
2. Use active predicates (verbs): "uses", "depends_on", "provides", "causes",
   "is_part_of", "implements", "stores", "manages", "communicates_with",
   "extends", "replaces", "triggers", "requires", "produces".
3. Classify entity types strictly as one of:
   PERSON | ORG | TECH | CONCEPT | ACTION | LOCATION
4. Assign confidence 0.0–1.0 based on how explicitly the relationship is stated.

Respond ONLY with a valid JSON array — no prose, no markdown fences.
Each element must have exactly these fields:
{
  "subject":      "<string>",
  "predicate":    "<string>",
  "object":       "<string>",
  "subject_type": "TECH|PERSON|ORG|CONCEPT|ACTION|LOCATION",
  "object_type":  "TECH|PERSON|ORG|CONCEPT|ACTION|LOCATION",
  "confidence":   0.0
}""".strip()

_MAX_LLM_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 0.5


# ──────────────────────────────────────────────────────────────────────────────
# LLMEntityExtractor — accurate triple extraction via LLM
# ──────────────────────────────────────────────────────────────────────────────

class LLMEntityExtractor:
    """
    Accurate triple extractor powered by an LLM.

    - Sends text to LLM with strict JSON output requirement.
    - Validates each item against the Triple Pydantic schema.
    - Retries up to ``_MAX_LLM_RETRIES`` times on schema violation.
    - Batch processing: groups multiple short texts into a single LLM call
      to reduce API round-trips and cost.

    The LLMBridge from Phase 1 is optional; if absent the extractor calls
    LiteLLM directly so the two modules remain loosely coupled.

    Usage::

        extractor = LLMEntityExtractor(llm_bridge=bridge)
        result = await extractor.extract("IronCore uses Docker for isolation.")
    """

    def __init__(
        self,
        llm_bridge: Any = None,
        model_id: str = "claude-haiku-3-5",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._llm_bridge = llm_bridge
        self._model_id = model_id
        self._timeout = timeout_seconds

    # ── Public API ────────────────────────────────────────────────────────────

    async def extract(self, text: str) -> ExtractionResult:
        """
        Extract entities and triples from a single text block via LLM.

        Args:
            text: Source text to analyze.

        Returns:
            ExtractionResult with both entities and triples populated.

        Raises:
            LLMExtractionError: All retries exhausted.
        """
        start_time = time.time()
        triples = await self._extract_triples_with_retry(text)
        entities = self._triples_to_entities(triples, text)
        elapsed_ms = (time.time() - start_time) * 1_000

        logger.info(
            "[LLMExtractor] len=%d | entities=%d triples=%d | %.1fms | model=%s",
            len(text), len(entities), len(triples), elapsed_ms, self._model_id,
        )
        return ExtractionResult(
            entities=entities,
            triples=triples,
            processing_time_ms=elapsed_ms,
            model_used=f"llm:{self._model_id}",
        )

    async def extract_batch(self, texts: List[str]) -> List[ExtractionResult]:
        """
        Extract from multiple texts, batching short ones into a single LLM call.

        Texts shorter than 200 characters are grouped into batches of 5
        to minimize API round-trips and token overhead.

        Args:
            texts: List of source text strings.

        Returns:
            List[ExtractionResult] — one entry per input text, same order.
        """
        results: List[Optional[ExtractionResult]] = [None] * len(texts)

        # Partition: short (batchable) vs. long (individual call)
        short_idxs = [i for i, t in enumerate(texts) if len(t) < 200]
        long_idxs  = [i for i, t in enumerate(texts) if len(t) >= 200]

        # Long texts — concurrent individual calls
        if long_idxs:
            long_tasks = [self.extract(texts[i]) for i in long_idxs]
            long_results = await asyncio.gather(*long_tasks, return_exceptions=True)
            for idx, res in zip(long_idxs, long_results):
                if isinstance(res, Exception):
                    logger.warning("[LLMExtractor] Long-text %d failed: %s", idx, res)
                    results[idx] = _empty_result(f"llm:{self._model_id}:failed")
                else:
                    results[idx] = res  # type: ignore[assignment]

        # Short texts — grouped batches of 5
        batch_size = 5
        for batch_start in range(0, len(short_idxs), batch_size):
            batch_idxs = short_idxs[batch_start : batch_start + batch_size]
            batch_texts = [texts[i] for i in batch_idxs]
            combined = "\n---\n".join(
                f"[{j + 1}] {t}" for j, t in enumerate(batch_texts)
            )
            try:
                t0 = time.time()
                triples = await self._extract_triples_with_retry(combined)
                elapsed_ms = (time.time() - t0) * 1_000
                per_text_ms = elapsed_ms / max(len(batch_idxs), 1)
                for global_i, src_text in zip(batch_idxs, batch_texts):
                    # Attribute triples whose subject or object appears in this text
                    relevant = [
                        tr for tr in triples
                        if tr.subject.lower() in src_text.lower()
                        or tr.object.lower() in src_text.lower()
                    ] or triples
                    results[global_i] = ExtractionResult(
                        entities=self._triples_to_entities(relevant, src_text),
                        triples=relevant,
                        processing_time_ms=per_text_ms,
                        model_used=f"llm:{self._model_id}:batch",
                    )
            except Exception as exc:
                logger.warning("[LLMExtractor] Batch failed: %s", exc)
                for global_i in batch_idxs:
                    results[global_i] = _empty_result(f"llm:{self._model_id}:failed")

        return [r if r is not None else _empty_result("empty") for r in results]

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _extract_triples_with_retry(self, text: str) -> List[Triple]:
        """Run LLM extraction with exponential-backoff retry."""
        last_error: Exception = LLMExtractionError("No attempts made.")
        for attempt in range(1, _MAX_LLM_RETRIES + 1):
            try:
                raw_json = await self._call_llm(text)
                return self._parse_triples(raw_json, text)
            except LLMExtractionError as exc:
                last_error = exc
                logger.warning(
                    "[LLMExtractor] Attempt %d/%d failed: %s",
                    attempt, _MAX_LLM_RETRIES, exc,
                )
                if attempt < _MAX_LLM_RETRIES:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

        raise LLMExtractionError(
            f"Extraction failed after {_MAX_LLM_RETRIES} attempts. "
            f"Last error: {last_error}"
        )

    async def _call_llm(self, text: str) -> str:
        """
        Invoke LLM and return raw JSON string.

        Priority:
          1. LLMBridge.call_llm() (Phase 1 — cost tracking, tier routing)
          2. Direct litellm.acompletion (standalone / no bridge)

        Returns:
            Raw response string from the LLM.

        Raises:
            LLMExtractionError: On network error or missing dependency.
        """
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract all entity relationships from this text:\n\n" + text
                ),
            },
        ]

        # ── Path 1: use LLMBridge from Phase 1 ───────────────────────────────
        if self._llm_bridge is not None:
            try:
                # Build a lightweight ModelConfig for haiku-tier extraction
                from ironcore.core.llm_bridge import ModelConfig as _MCfg  # local import

                mc = _MCfg(
                    model_id=self._model_id,
                    max_input_tokens=8_000,
                    max_output_tokens=2_048,
                    temperature=0.0,
                    timeout_seconds=self._timeout,
                )
                response = await asyncio.wait_for(
                    self._llm_bridge.call_llm(messages=messages, model_config=mc),
                    timeout=self._timeout,
                )
                return response.content
            except Exception as exc:
                logger.warning(
                    "[LLMExtractor] LLMBridge failed, falling back to litellm direct: %s", exc
                )

        # ── Path 2: direct LiteLLM ────────────────────────────────────────────
        try:
            import litellm  # type: ignore[import]

            raw = await asyncio.wait_for(
                litellm.acompletion(
                    model=self._model_id,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=2_048,
                ),
                timeout=self._timeout,
            )
            return (raw.choices[0].message.content or "").strip()
        except ImportError as exc:
            raise LLMExtractionError(
                "litellm is required. Install with: pip install litellm"
            ) from exc
        except Exception as exc:
            raise LLMExtractionError(f"LiteLLM call failed: {exc}") from exc

    def _parse_triples(self, raw_json: str, source_text: str) -> List[Triple]:
        """
        Parse and validate LLM JSON output → list of Triple objects.

        Strips markdown fences. Accepts both JSON arrays and single objects.
        Silently drops malformed items rather than failing the whole batch.
        """
        # Strip ``` or ```json fences the model may add
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$", "", raw_json.strip(), flags=re.MULTILINE
        )

        # Find the first JSON array in the response
        arr_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if arr_match:
            cleaned = arr_match.group(0)
        else:
            # Wrap a lone JSON object in an array
            obj_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if obj_match:
                cleaned = f"[{obj_match.group(0)}]"
            else:
                raise LLMExtractionError(
                    f"No JSON found in LLM response: {raw_json[:300]!r}"
                )

        try:
            items = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMExtractionError(
                f"JSON parse error: {exc}\nCleaned: {cleaned[:400]!r}"
            ) from exc

        if not isinstance(items, list):
            items = [items]

        triples: List[Triple] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                subj_type = str(item.get("subject_type", "CONCEPT")).upper()
                obj_type  = str(item.get("object_type",  "CONCEPT")).upper()
                if subj_type not in _VALID_ENTITY_TYPES:
                    subj_type = "CONCEPT"
                if obj_type not in _VALID_ENTITY_TYPES:
                    obj_type = "CONCEPT"

                triple = Triple(
                    subject=str(item.get("subject", "")).strip(),
                    predicate=str(item.get("predicate", "")).strip(),
                    object=str(item.get("object", "")).strip(),
                    subject_type=subj_type,
                    object_type=obj_type,
                    source_text=source_text[:500],
                    confidence=float(item.get("confidence", 0.8)),
                )
                if triple.subject and triple.predicate and triple.object:
                    triples.append(triple)
            except Exception as exc:
                logger.debug("[LLMExtractor] Skipping malformed item %s: %s", item, exc)

        logger.debug(
            "[LLMExtractor] Parsed %d/%d valid triples", len(triples), len(items)
        )
        return triples

    @staticmethod
    def _triples_to_entities(triples: List[Triple], text: str) -> List[EntitySpan]:
        """
        Derive unique EntitySpan objects by collecting all subjects and objects.

        Character offsets are estimated by searching `text` for the entity name.
        """
        seen: Dict[str, EntitySpan] = {}

        def _find_span(name: str, entity_type: str) -> EntitySpan:
            pos = text.find(name)
            if pos == -1:
                pos = text.lower().find(name.lower())
            start = max(0, pos)
            return EntitySpan(
                text=name,
                entity_type=entity_type,
                start=start,
                end=start + len(name),
                confidence=0.85,
            )

        for triple in triples:
            for name, etype in (
                (triple.subject, triple.subject_type),
                (triple.object, triple.object_type),
            ):
                key = name.lower()
                if key and key not in seen:
                    seen[key] = _find_span(name, etype)

        return list(seen.values())


# ──────────────────────────────────────────────────────────────────────────────
# HybridEntityExtractor — main public interface
# ──────────────────────────────────────────────────────────────────────────────

# Routing threshold: texts below this length go to FastExtractor
_FAST_CHAR_THRESHOLD = 300

# Sentinel for empty / failed results
def _empty_result(model_used: str = "empty") -> ExtractionResult:
    return ExtractionResult(
        entities=[], triples=[], processing_time_ms=0.0, model_used=model_used
    )


class HybridEntityExtractor:
    """
    Main entity extraction interface for IronCore's Brain layer.

    Routing rules:
      - text < 300 chars  → FastEntityExtractor  (local, instant, entities only)
      - text ≥ 300 chars  → LLMEntityExtractor   (accurate, with triples)
      - LLM failure       → automatic fall-through to FastEntityExtractor
      - All results are cached by SHA-256 content hash.

    Integration with Phase 2:
      GraphRAGMemory.add_interaction() accepts an optional `entity_extractor`
      argument. When provided, it delegates to this class instead of the old
      `_extract_simple_entities()` heuristic.

    Usage::

        extractor = await HybridEntityExtractor.create()
        result = await extractor.extract("IronCore uses Docker for isolation.")
        # result.entities → [EntitySpan(text="IronCore", entity_type="TECH", ...),
        #                    EntitySpan(text="Docker",   entity_type="TECH", ...)]
        # result.triples  → [Triple(subject="IronCore", predicate="uses",
        #                           object="Docker", ...)]

    Advanced (with LLMBridge from Phase 1 for cost tracking)::

        extractor = await HybridEntityExtractor.create(llm_bridge=bridge)
    """

    def __init__(
        self,
        fast_extractor: FastEntityExtractor,
        llm_extractor: LLMEntityExtractor,
    ) -> None:
        self._fast = fast_extractor
        self._llm = llm_extractor
        self._cache: Dict[str, ExtractionResult] = {}

    @classmethod
    async def create(
        cls,
        spacy_model: str = "en_core_web_sm",
        llm_model_id: str = "claude-haiku-3-5",
        llm_bridge: Any = None,
    ) -> "HybridEntityExtractor":
        """
        Async factory: initialize sub-extractors and return a ready instance.

        Args:
            spacy_model:  spaCy model name for FastEntityExtractor.
            llm_model_id: LiteLLM model string for LLMEntityExtractor.
            llm_bridge:   Optional LLMBridge from Phase 1 (adds cost tracking).
        """
        fast = FastEntityExtractor(model_name=spacy_model)
        await fast.initialize()
        llm = LLMEntityExtractor(llm_bridge=llm_bridge, model_id=llm_model_id)
        instance = cls(fast_extractor=fast, llm_extractor=llm)
        logger.info(
            "[HybridExtractor] Ready | spacy=%s llm=%s", spacy_model, llm_model_id
        )
        return instance

    # ── Public API ────────────────────────────────────────────────────────────

    async def extract(self, text: str) -> ExtractionResult:
        """
        Extract entities (and possibly triples) from `text`.

        - Short text → FastEntityExtractor (entities only, no LLM, sub-ms).
        - Long text  → LLMEntityExtractor (entities + triples).
        - LLM errors → silently fall back to FastEntityExtractor.
        - Identical texts return cached results instantly.

        Args:
            text: Source text to analyze.

        Returns:
            ExtractionResult with entities (always) and triples (for long text).
        """
        if not text or not text.strip():
            return _empty_result("empty")

        cache_key = hashlib.sha256(text.encode()).hexdigest()
        if cache_key in self._cache:
            logger.debug("[HybridExtractor] Cache hit | text_len=%d", len(text))
            return self._cache[cache_key]

        if len(text) < _FAST_CHAR_THRESHOLD:
            result = await self._fast.extract(text)
        else:
            try:
                result = await self._llm.extract(text)
            except LLMExtractionError as exc:
                logger.warning(
                    "[HybridExtractor] LLM failed, falling back to fast: %s", exc
                )
                result = await self._fast.extract(text)

        self._cache[cache_key] = result
        logger.info(
            "[HybridExtractor] text_len=%d | entities=%d triples=%d | "
            "%.1fms | model=%s | cache_size=%d",
            len(text),
            len(result.entities),
            len(result.triples),
            result.processing_time_ms,
            result.model_used,
            len(self._cache),
        )
        return result

    def clear_cache(self) -> None:
        """Evict all cached extraction results."""
        self._cache.clear()
        logger.info("[HybridExtractor] Cache cleared.")

    @property
    def cache_size(self) -> int:
        """Number of cached extraction results currently in memory."""
        return len(self._cache)
