"""Phase 3 smoke tests — run with: python3 test_phase3.py"""
import asyncio, inspect, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from ironcore.core.entity_extractor import (
    EntitySpan, Triple, ExtractionResult,
    FastEntityExtractor, HybridEntityExtractor, _FAST_CHAR_THRESHOLD,
)
import ironcore.memory.graph_rag as g

RESULTS = []

def ok(msg):
    print(f"PASS  {msg}")
    RESULTS.append(True)

def fail(msg):
    print(f"FAIL  {msg}")
    RESULTS.append(False)

# 1 — imports
ok("imports")

# 2 — Pydantic models
span = EntitySpan(text="Docker", entity_type="TECH", start=0, end=6, confidence=0.9)
t = Triple(subject="IronCore", predicate="uses", object="Docker",
           subject_type="TECH", object_type="TECH",
           source_text="IronCore uses Docker.", confidence=0.95)
r = ExtractionResult(entities=[span], triples=[t], processing_time_ms=5.0, model_used="test")
assert r.entities[0].text == "Docker" and r.triples[0].predicate == "uses"
ok("Pydantic models")

# 3 — FastEntityExtractor regex fallback
async def test3():
    fast = FastEntityExtractor()
    await fast.initialize()
    res = await fast.extract("IronCore uses Docker for sandbox isolation with Python.")
    names = [e.text.lower() for e in res.entities]
    assert any("docker" in n for n in names), f"docker missing: {names}"
    assert res.triples == [], "FastExtractor must not produce triples"
    ok(f"FastExtractor regex: {names[:5]}")
asyncio.run(test3())

# 4 — HybridExtractor short path (no LLM)
async def test4():
    ex = await HybridEntityExtractor.create()
    short = "Docker isolates processes."
    assert len(short) < _FAST_CHAR_THRESHOLD
    res = await ex.extract(short)
    assert isinstance(res, ExtractionResult)
    ok(f"Hybrid short path: {[e.text for e in res.entities]}")
asyncio.run(test4())

# 5 — Content-hash cache
async def test5():
    ex = await HybridEntityExtractor.create()
    txt = "spaCy and Pydantic are used in IronCore."
    await ex.extract(txt)
    await ex.extract(txt)
    assert ex.cache_size == 1
    ex.clear_cache()
    assert ex.cache_size == 0
    ok("Content-hash caching")
asyncio.run(test5())

# 6 — Empty text guard
async def test6():
    ex = await HybridEntityExtractor.create()
    res = await ex.extract("")
    assert res.entities == [] and res.triples == []
    ok("Empty text guard")
asyncio.run(test6())

# 7 — GraphStore Phase 2 backward-compat
gs = g.GraphStore()
n1 = g.KnowledgeNode(entity_type="tech", name="Docker")
n2 = g.KnowledgeNode(entity_type="concept", name="Isolation")
gs.add_node(n1); gs.add_node(n2)
gs.add_edge(g.KnowledgeEdge(source_id=n1.id, target_id=n2.id, relationship="provides"))
assert len(gs.get_neighbors(n1.id)) == 1
ok("GraphStore Phase 2 backward-compat")

# 8 — GraphRAGMemory new signatures
sig1 = inspect.signature(g.GraphRAGMemory.__init__)
sig2 = inspect.signature(g.GraphRAGMemory.create)
assert "entity_extractor" in sig1.parameters
assert "entity_extractor" in sig2.parameters
ok("GraphRAGMemory new signatures")

# 9 — entity_extractor wiring
async def test9():
    ex = await HybridEntityExtractor.create()
    graph = g.GraphStore()
    vs = g.VectorStore.__new__(g.VectorStore)
    vs._initialized = False
    ret = g.HybridRetriever(vs, graph)
    mem = g.GraphRAGMemory(vs, graph, ret, entity_extractor=ex)
    assert mem._entity_extractor is ex
    ok("GraphRAGMemory.entity_extractor wiring")
asyncio.run(test9())

# 10 — Existing Phase 2 test suite (stable_id, GraphStore)
from ironcore.memory.graph_rag import _stable_id
assert _stable_id("Docker") == _stable_id("docker")
ok("stable_id case-insensitive")

print()
passed = sum(RESULTS)
total  = len(RESULTS)
print("=" * 50)
print(f"  {passed}/{total} PHASE 3 TESTS PASSED")
print("=" * 50)
sys.exit(0 if all(RESULTS) else 1)
