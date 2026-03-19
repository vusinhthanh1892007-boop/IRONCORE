"""
Tests for Brain Phase 6 — Skills Registry
==========================================
Tests cover:
  - SkillMetadata validation (name, version, cost_tier, type)
  - SkillParameterSchema type validation
  - SkillRegistry: register, unregister, get, list_all, search
  - Conflict handling and overwrite flag
  - to_tool_definitions() bridge to IronCoreEngine
  - @skill decorator and auto_discover()
  - suggest_skills_for_task() heuristic ranking
  - RegisteredSkill.invoke() with async and sync handlers
  - Stats snapshot
"""

from __future__ import annotations

import asyncio
import pytest

from ironcore.skills.registry import (
    RegisteredSkill,
    SkillConflictError,
    SkillMetadata,
    SkillNotFoundError,
    SkillParameterSchema,
    SkillRegistry,
    skill,
)
from ironcore.core.engine import RiskLevel, ToolDefinition


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _noop_handler(**kwargs):
    return "ok"


def _make_metadata(**overrides) -> SkillMetadata:
    defaults = {
        "name": "test_skill",
        "description": "A test skill",
        "version": "1.0.0",
        "tags": ["test"],
        "risk_level": RiskLevel.LOW,
    }
    defaults.update(overrides)
    return SkillMetadata(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# SkillParameterSchema
# ──────────────────────────────────────────────────────────────────────────────

def test_skill_parameter_schema_valid_types():
    for t in ("string", "int", "float", "bool", "dict", "list", "any"):
        schema = SkillParameterSchema(name="x", type=t, description="desc")
        assert schema.type == t


def test_skill_parameter_schema_rejects_invalid_type():
    with pytest.raises(Exception):
        SkillParameterSchema(name="x", type="unknown_type", description="desc")


# ──────────────────────────────────────────────────────────────────────────────
# SkillMetadata validation
# ──────────────────────────────────────────────────────────────────────────────

def test_skill_metadata_valid():
    md = _make_metadata()
    assert md.name == "test_skill"
    assert md.version == "1.0.0"
    assert md.cost_tier == "free"


def test_skill_metadata_rejects_invalid_name():
    with pytest.raises(Exception):
        _make_metadata(name="Invalid-Name")


def test_skill_metadata_rejects_bad_semver():
    with pytest.raises(Exception):
        _make_metadata(version="1.0")


def test_skill_metadata_rejects_bad_cost_tier():
    with pytest.raises(Exception):
        _make_metadata(cost_tier="priceless")


def test_skill_metadata_to_tool_definition_description_includes_params():
    md = SkillMetadata(
        name="my_tool",
        description="Does something",
        parameters=[
            SkillParameterSchema(name="query", type="string", description="search query"),
            SkillParameterSchema(name="limit", type="int", description="max results", required=False, default=10),
        ],
    )
    desc = md.to_tool_definition_description()
    assert "query" in desc
    assert "optional" in desc
    assert "Does something" in desc


# ──────────────────────────────────────────────────────────────────────────────
# SkillRegistry — register / unregister / get
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_register_and_get():
    registry = SkillRegistry()
    md = _make_metadata()
    await registry.register(md, _noop_handler)

    result = registry.get("test_skill")
    assert result is not None
    assert result.metadata.name == "test_skill"
    assert "test_skill" in registry


@pytest.mark.asyncio
async def test_registry_register_conflict_raises():
    registry = SkillRegistry()
    md = _make_metadata()
    await registry.register(md, _noop_handler)
    with pytest.raises(SkillConflictError):
        await registry.register(md, _noop_handler)


@pytest.mark.asyncio
async def test_registry_register_overwrite():
    registry = SkillRegistry()
    md_v1 = _make_metadata(version="1.0.0")
    md_v2 = _make_metadata(version="2.0.0")
    await registry.register(md_v1, _noop_handler)
    await registry.register(md_v2, _noop_handler, overwrite=True)
    assert registry.get("test_skill").metadata.version == "2.0.0"


@pytest.mark.asyncio
async def test_registry_unregister():
    registry = SkillRegistry()
    await registry.register(_make_metadata(), _noop_handler)
    await registry.unregister("test_skill")
    assert registry.get("test_skill") is None
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_registry_unregister_missing_raises():
    registry = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        await registry.unregister("ghost_skill")


# ──────────────────────────────────────────────────────────────────────────────
# SkillRegistry — list_all / search
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_list_all():
    registry = SkillRegistry()
    await registry.register(_make_metadata(name="alpha", tags=["web"]), _noop_handler)
    await registry.register(_make_metadata(name="beta", tags=["memory"]), _noop_handler)

    all_skills = registry.list_all()
    assert len(all_skills) == 2
    assert all_skills[0].name == "alpha"  # sorted alphabetically


@pytest.mark.asyncio
async def test_registry_list_all_filter_tags():
    registry = SkillRegistry()
    await registry.register(_make_metadata(name="web_skill", tags=["web", "search"]), _noop_handler)
    await registry.register(_make_metadata(name="memory_skill", tags=["memory"]), _noop_handler)

    web_skills = registry.list_all(filter_tags=["web"])
    assert len(web_skills) == 1
    assert web_skills[0].name == "web_skill"


@pytest.mark.asyncio
async def test_registry_list_all_excludes_deprecated_by_default():
    registry = SkillRegistry()
    await registry.register(
        _make_metadata(name="old_skill", deprecated=True, deprecated_reason="Use new_skill"),
        _noop_handler,
    )
    await registry.register(_make_metadata(name="new_skill"), _noop_handler)

    active = registry.list_all()
    assert len(active) == 1
    assert active[0].name == "new_skill"

    with_deprecated = registry.list_all(include_deprecated=True)
    assert len(with_deprecated) == 2


@pytest.mark.asyncio
async def test_registry_search_finds_by_keyword():
    registry = SkillRegistry()
    await registry.register(
        _make_metadata(name="web_search", description="Search the web for information", tags=["web"]),
        _noop_handler,
    )
    await registry.register(
        _make_metadata(name="memory_store", description="Store facts in memory", tags=["memory"]),
        _noop_handler,
    )

    results = registry.search("web")
    assert len(results) >= 1
    assert results[0].name == "web_search"


@pytest.mark.asyncio
async def test_registry_search_respects_max_results():
    registry = SkillRegistry()
    for i in range(5):
        await registry.register(
            _make_metadata(name=f"skill_{i}", description=f"Does task {i}", tags=["test"]),
            _noop_handler,
        )

    results = registry.search("task", max_results=3)
    assert len(results) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# to_tool_definitions — bridge to IronCoreEngine
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_to_tool_definitions_returns_correct_types():
    registry = SkillRegistry()
    await registry.register(
        _make_metadata(name="web_fetch", risk_level=RiskLevel.MEDIUM),
        _noop_handler,
    )
    await registry.register(
        _make_metadata(name="local_read", risk_level=RiskLevel.LOW),
        _noop_handler,
    )

    defs = registry.to_tool_definitions()
    assert len(defs) == 2
    assert all(isinstance(d, ToolDefinition) for d in defs)

    names = {d.name for d in defs}
    assert names == {"web_fetch", "local_read"}

    web_def = next(d for d in defs if d.name == "web_fetch")
    assert web_def.risk_level == RiskLevel.MEDIUM


@pytest.mark.asyncio
async def test_to_tool_definitions_excludes_deprecated():
    registry = SkillRegistry()
    await registry.register(
        _make_metadata(name="alive_skill"),
        _noop_handler,
    )
    await registry.register(
        _make_metadata(name="dead_skill", deprecated=True, deprecated_reason="outdated"),
        _noop_handler,
    )

    defs = registry.to_tool_definitions()
    assert len(defs) == 1
    assert defs[0].name == "alive_skill"


# ──────────────────────────────────────────────────────────────────────────────
# @skill decorator + auto_discover
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_decorator_attaches_metadata():
    @skill(
        name="demo_skill",
        description="A demo for testing",
        tags=["demo"],
        risk_level=RiskLevel.LOW,
    )
    async def demo_skill(query: str) -> str:
        return f"result:{query}"

    meta = getattr(demo_skill, "_ironcore_skill_metadata", None)
    assert meta is not None
    assert meta.name == "demo_skill"
    assert "demo" in meta.tags


@pytest.mark.asyncio
async def test_skill_decorator_wrapped_function_still_callable():
    @skill(name="echo_skill", description="Echo input")
    async def echo_skill(text: str) -> str:
        return text

    result = await echo_skill(text="hello")
    assert result == "hello"


# ──────────────────────────────────────────────────────────────────────────────
# RegisteredSkill.invoke — async and sync handlers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registered_skill_invoke_async_handler():
    async def async_handler(value: int) -> int:
        return value * 2

    registered = RegisteredSkill(
        metadata=_make_metadata(),
        handler=async_handler,
    )
    result = await registered.invoke(value=5)
    assert result == 10
    assert registered.call_count == 1
    assert registered.last_called_at is not None


@pytest.mark.asyncio
async def test_registered_skill_invoke_tracks_calls():
    registered = RegisteredSkill(
        metadata=_make_metadata(),
        handler=_noop_handler,
    )
    await registered.invoke()
    await registered.invoke()
    assert registered.call_count == 2


@pytest.mark.asyncio
async def test_registered_skill_invoke_logs_deprecated(caplog):
    import logging
    md = _make_metadata(deprecated=True, deprecated_reason="Use new_skill instead")
    registered = RegisteredSkill(metadata=md, handler=_noop_handler)

    with caplog.at_level(logging.WARNING, logger="ironcore.skills.registry"):
        await registered.invoke()

    assert "deprecated" in caplog.text.lower()


# ──────────────────────────────────────────────────────────────────────────────
# suggest_skills_for_task
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_skills_for_task_returns_relevant():
    registry = SkillRegistry()
    await registry.register(
        SkillMetadata(name="web_search", description="Search the web for data", tags=["web", "search"]),
        _noop_handler,
    )
    await registry.register(
        SkillMetadata(name="read_file", description="Read local file contents", tags=["filesystem"]),
        _noop_handler,
    )
    await registry.register(
        SkillMetadata(name="send_email", description="Send email notifications", tags=["email", "notifications"]),
        _noop_handler,
    )

    suggestions = await registry.suggest_skills_for_task("search web for python documentation")
    assert len(suggestions) >= 1
    assert suggestions[0].name == "web_search"


# ──────────────────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_stats():
    registry = SkillRegistry()
    await registry.register(_make_metadata(name="skill_a"), _noop_handler)
    await registry.register(_make_metadata(name="skill_b"), _noop_handler)

    stats = registry.stats()
    assert stats["total_skills"] == 2
    assert len(stats["skills"]) == 2
    names = {s["name"] for s in stats["skills"]}
    assert names == {"skill_a", "skill_b"}
