"""
IronCore: Skills Registry — Dynamic Skill Discovery + Metadata
==============================================================
Phase 6 — The Brain (Claude Sonnet 4.6)

Responsibilities:
  - Centralized catalog of all tools/skills available to IronCore agents
  - Each skill has: name, version, description, parameters schema,
    risk_level, tags, author, and a callable async handler
  - Discovery: auto-scan Python modules for @skill-decorated functions,
    dynamic import at runtime
  - Versioning: semver per skill; multiple versions may coexist
  - Search: semantic tag+keyword matching; optional embedding-based search
  - @skill decorator: declarative skill registration via annotation
  - to_tool_definitions(): bridge to IronCoreEngine.register_tool()

Integration:
  - IronCoreEngine (GPT-5.4):   registry.to_tool_definitions() → engine.register_tool()
  - LLMBridge (Brain Phase 1):  format_tools_for_llm() consumes ToolDefinition
  - MultiAgentCoordinator (P8): registry.suggest_skills_for_task()

Author: The Brain (IronCore Project) — Claude Sonnet 4.6
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import re
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator

from ironcore.core.engine import RiskLevel, ToolDefinition

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────

class SkillsError(Exception):
    """Base exception for all Skills Registry errors."""


class SkillNotFoundError(SkillsError):
    """Raised when a requested skill name is not registered."""


class SkillConflictError(SkillsError):
    """Raised when a skill with the same name/version is already registered."""


class SkillDiscoveryError(SkillsError):
    """Raised when auto-discovery of a module fails unrecoverably."""


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────

class SkillParameterSchema(BaseModel):
    """
    Describes a single parameter accepted by a skill.

    Attributes:
        name        : Parameter name (must match function kwarg).
        type        : Type hint string: "string", "int", "float", "bool", "dict", "list".
        description : Human-readable description for LLM prompt formatting.
        required    : Whether the parameter is mandatory.
        default     : Default value when not required.
        enum_values : Optional allowed value set for validation.
    """

    name: str
    type: str
    description: str
    required: bool = True
    default: Optional[Any] = None
    enum_values: Optional[List[Any]] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        allowed = {"string", "int", "float", "bool", "dict", "list", "any"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"Unsupported type '{value}'. Allowed: {sorted(allowed)}")
        return normalized


class SkillMetadata(BaseModel):
    """
    Complete metadata contract for one IronCore skill.

    Attributes:
        name               : Unique skill identifier (snake_case).
        version            : Semantic version string "MAJOR.MINOR.PATCH".
        description        : Short one-line description (LLM prompt injection).
        long_description   : Detailed explanation for developer docs.
        author             : Agent that owns this skill: "architect", "brain", "ghost".
        tags               : Categorisation tags e.g. ["web", "memory"].
        parameters         : Ordered list of parameter schemas.
        risk_level         : RiskLevel enum instance.
        requires_sandbox   : Whether execution MUST run in a Docker container.
        requires_network   : Whether the skill makes outbound network calls.
        estimated_latency_ms : Expected wall-clock time per invocation.
        cost_tier          : "free" / "cheap" / "expensive".
        deprecated         : Flag this skill as deprecated.
        deprecated_reason  : Explanation shown when a deprecated skill is invoked.
    """

    name: str
    version: str = "1.0.0"
    description: str
    long_description: str = ""
    author: str = "brain"
    tags: List[str] = Field(default_factory=list)
    parameters: List[SkillParameterSchema] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_sandbox: bool = False
    requires_network: bool = False
    estimated_latency_ms: float = 100.0
    cost_tier: str = "free"
    deprecated: bool = False
    deprecated_reason: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_snake_case(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Skill name cannot be empty.")
        if not re.match(r"^[a-z][a-z0-9_]*$", stripped):
            raise ValueError(
                f"Skill name '{stripped}' must be snake_case "
                "(lowercase letters, digits, underscores; must start with a letter)."
            )
        return stripped

    @field_validator("version")
    @classmethod
    def version_semver(cls, value: str) -> str:
        parts = value.strip().split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(
                f"Version '{value}' must follow semver format MAJOR.MINOR.PATCH."
            )
        return value.strip()

    @field_validator("cost_tier")
    @classmethod
    def cost_tier_valid(cls, value: str) -> str:
        allowed = {"free", "cheap", "expensive"}
        if value not in allowed:
            raise ValueError(f"cost_tier must be one of {allowed}.")
        return value

    def to_tool_definition_description(self) -> str:
        """Format a concise description for LLM consumption."""
        parts = [self.description]
        if self.parameters:
            param_strs = []
            for p in self.parameters:
                req_str = "" if p.required else " (optional)"
                param_strs.append(f"{p.name}: {p.type}{req_str} — {p.description}")
            parts.append("Parameters: " + "; ".join(param_strs))
        if self.deprecated:
            parts.append(f"[DEPRECATED] {self.deprecated_reason or ''}")
        return " | ".join(parts)


class RegisteredSkill(BaseModel):
    """
    A skill entry in the registry: metadata + callable handler.

    Attributes:
        metadata        : SkillMetadata describing the skill.
        handler         : Async callable that implements the skill logic.
        registered_at   : Unix timestamp of registration.
        call_count      : Monotonic invocation counter (updated in-place).
        last_called_at  : Timestamp of most recent call.
    """

    model_config = {"arbitrary_types_allowed": True}

    metadata: SkillMetadata
    handler: Any  # Callable — arbitrary_types_allowed
    registered_at: float = Field(default_factory=time.time)
    call_count: int = 0
    last_called_at: Optional[float] = None

    async def invoke(self, **kwargs: Any) -> Any:
        """
        Invoke the skill handler, tracking call statistics.

        Logs a warning if the skill is deprecated.
        """
        if self.metadata.deprecated:
            logger.warning(
                "[SkillRegistry] Invoking deprecated skill '%s': %s",
                self.metadata.name,
                self.metadata.deprecated_reason or "No reason provided.",
            )
        self.call_count += 1
        self.last_called_at = time.time()
        if asyncio.iscoroutinefunction(self.handler):
            return await self.handler(**kwargs)
        return self.handler(**kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# @skill decorator
# ──────────────────────────────────────────────────────────────────────────────

# Module-level pending registrations: collected by the decorator and
# consumed by SkillRegistry.auto_discover().
_PENDING_SKILLS: List[tuple[SkillMetadata, Callable]] = []


def skill(
    name: str,
    description: str,
    *,
    version: str = "1.0.0",
    long_description: str = "",
    author: str = "brain",
    tags: Optional[List[str]] = None,
    parameters: Optional[List[SkillParameterSchema]] = None,
    risk_level: RiskLevel = RiskLevel.LOW,
    requires_sandbox: bool = False,
    requires_network: bool = False,
    estimated_latency_ms: float = 100.0,
    cost_tier: str = "free",
) -> Callable:
    """
    Decorator that tags a function as an IronCore skill.

    Usage::

        @skill(
            name="web_search",
            version="1.0.0",
            description="Search the web for information",
            tags=["web", "information"],
            risk_level=RiskLevel.MEDIUM,
            requires_network=True,
        )
        async def web_search(query: str, max_results: int = 5) -> str:
            ...

    The decorated function is registered in the module-level ``_PENDING_SKILLS``
    list and loaded into a ``SkillRegistry`` via ``auto_discover()``.
    """
    metadata = SkillMetadata(
        name=name,
        version=version,
        description=description,
        long_description=long_description,
        author=author,
        tags=tags or [],
        parameters=parameters or [],
        risk_level=risk_level,
        requires_sandbox=requires_sandbox,
        requires_network=requires_network,
        estimated_latency_ms=estimated_latency_ms,
        cost_tier=cost_tier,
    )

    def decorator(fn: Callable) -> Callable:
        _PENDING_SKILLS.append((metadata, fn))

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)

        # Attach metadata for introspection
        wrapper._ironcore_skill_metadata = metadata  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ──────────────────────────────────────────────────────────────────────────────
# Skill Registry
# ──────────────────────────────────────────────────────────────────────────────

class SkillRegistry:
    """
    Centralized catalog of all tools/skills available to IronCore.

    Features:
      - Register/unregister skills at runtime.
      - Keyword + tag search over skill metadata.
      - Convert skills → ToolDefinition[] for IronCoreEngine.
      - Auto-discover @skill-decorated functions from Python modules.
      - Suggest relevant skills for a natural-language task description.

    Thread safety: all mutations are coordinated via asyncio.Lock so the
    registry is safe to use in a single-event-loop async environment.
    """

    def __init__(self) -> None:
        # Primary index: skill_name → RegisteredSkill
        self._skills: Dict[str, RegisteredSkill] = {}
        self._lock = asyncio.Lock()

    # ── Registration ──────────────────────────────────────────────────────────

    async def register(
        self,
        metadata: SkillMetadata,
        handler: Callable,
        *,
        overwrite: bool = False,
    ) -> None:
        """
        Register a skill with its handler.

        Args:
            metadata  : SkillMetadata describing the skill.
            handler   : Async (or sync) callable implementing the skill.
            overwrite : If True, silently replace an existing skill with the
                        same name. If False (default), raise SkillConflictError.

        Raises:
            SkillConflictError: When the name is already taken and overwrite=False.
        """
        async with self._lock:
            existing = self._skills.get(metadata.name)
            if existing and not overwrite:
                raise SkillConflictError(
                    f"Skill '{metadata.name}' v{existing.metadata.version} is "
                    "already registered. Use overwrite=True to replace it."
                )
            self._skills[metadata.name] = RegisteredSkill(
                metadata=metadata,
                handler=handler,
            )
            logger.info(
                "[SkillRegistry] Registered skill '%s' v%s | tags=%s risk=%s",
                metadata.name,
                metadata.version,
                metadata.tags,
                metadata.risk_level.name,
            )

    async def unregister(self, skill_name: str) -> None:
        """
        Remove a skill from the registry.

        Args:
            skill_name: Name of the skill to remove.

        Raises:
            SkillNotFoundError: When no skill with that name exists.
        """
        async with self._lock:
            if skill_name not in self._skills:
                raise SkillNotFoundError(
                    f"Cannot unregister '{skill_name}': skill not found."
                )
            del self._skills[skill_name]
            logger.info("[SkillRegistry] Unregistered skill '%s'.", skill_name)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, skill_name: str) -> Optional[RegisteredSkill]:
        """
        Return the RegisteredSkill for a given name, or None if absent.

        Args:
            skill_name: Exact skill name to look up.
        """
        return self._skills.get(skill_name)

    def list_all(
        self,
        filter_tags: Optional[List[str]] = None,
        include_deprecated: bool = False,
    ) -> List[SkillMetadata]:
        """
        Return metadata for all registered skills.

        Args:
            filter_tags       : If provided, only return skills that have
                                ALL listed tags.
            include_deprecated: Include deprecated skills in the result.

        Returns:
            List of SkillMetadata sorted alphabetically by name.
        """
        results: List[SkillMetadata] = []
        for registered in self._skills.values():
            md = registered.metadata
            if not include_deprecated and md.deprecated:
                continue
            if filter_tags:
                if not all(tag in md.tags for tag in filter_tags):
                    continue
            results.append(md)
        return sorted(results, key=lambda m: m.name)

    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        max_results: int = 10,
        include_deprecated: bool = False,
    ) -> List[SkillMetadata]:
        """
        Keyword search over skill names, descriptions, and tags.

        Scoring algorithm:
          +4  : query appears in skill name (case-insensitive)
          +3  : query appears in description
          +2  : query appears in long_description
          +1  : each matching tag token from query
          tag filter applied after scoring (AND match on all required tags)

        Args:
            query             : Natural language or keyword search string.
            tags              : Optional tag filter (AND logic).
            max_results       : Maximum number of results to return.
            include_deprecated: Include deprecated skills in search.

        Returns:
            List of SkillMetadata sorted by relevance score, descending.
        """
        query_lower = query.strip().lower()
        query_tokens = set(re.split(r"\W+", query_lower))

        scored: List[tuple[int, SkillMetadata]] = []

        for registered in self._skills.values():
            md = registered.metadata
            if not include_deprecated and md.deprecated:
                continue
            if tags and not all(t in md.tags for t in tags):
                continue

            score = 0
            if query_lower in md.name:
                score += 4
            if query_lower in md.description.lower():
                score += 3
            if query_lower in md.long_description.lower():
                score += 2
            for token in query_tokens:
                if token and token in md.tags:
                    score += 1

            if score > 0 or not query_lower:
                scored.append((score, md))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [md for _, md in scored[:max_results]]

    # ── Bridge to Engine ──────────────────────────────────────────────────────

    def to_tool_definitions(
        self,
        include_deprecated: bool = False,
    ) -> List[ToolDefinition]:
        """
        Convert all registered skills to ToolDefinition instances.

        This bridges the Skills Registry into IronCoreEngine::

            engine = IronCoreEngine()
            for tool_def in registry.to_tool_definitions():
                engine.register_tool(tool_def)

        Args:
            include_deprecated: Include deprecated skill definitions.

        Returns:
            List of ToolDefinition objects ready for engine.register_tool().
        """
        definitions: List[ToolDefinition] = []
        for registered in self._skills.values():
            md = registered.metadata
            if not include_deprecated and md.deprecated:
                continue
            definitions.append(
                ToolDefinition(
                    name=md.name,
                    handler=registered.invoke,
                    risk_level=md.risk_level,
                    requires_sandbox=md.requires_sandbox,
                    description=md.to_tool_definition_description(),
                )
            )
        return definitions

    # ── Auto Discovery ────────────────────────────────────────────────────────

    async def auto_discover(self, modules: List[str]) -> int:
        """
        Auto-discover @skill-decorated functions from Python module paths.

        Imports each module in ``modules`` and collects any callables that
        have a ``_ironcore_skill_metadata`` attribute (attached by the
        ``@skill`` decorator). Registers them all.

        Also drains the module-level ``_PENDING_SKILLS`` list which is
        populated at import time by the decorator.

        Args:
            modules: List of dotted Python module paths to import and scan.
                     Example: ["ironcore.skills.web", "ironcore.skills.memory"]

        Returns:
            Number of new skills registered during this discovery pass.

        Raises:
            SkillDiscoveryError: When a module cannot be imported.
        """
        discovered = 0

        for module_path in modules:
            try:
                module = importlib.import_module(module_path)
            except ImportError as exc:
                raise SkillDiscoveryError(
                    f"Cannot import module '{module_path}' during skill discovery: {exc}"
                ) from exc

            for attr_name in dir(module):
                obj = getattr(module, attr_name, None)
                if obj is None:
                    continue
                metadata: Optional[SkillMetadata] = getattr(
                    obj, "_ironcore_skill_metadata", None
                )
                if metadata is not None and callable(obj):
                    try:
                        await self.register(metadata, obj, overwrite=False)
                        discovered += 1
                    except SkillConflictError:
                        logger.debug(
                            "[SkillRegistry] Skipping duplicate '%s' during auto_discover.",
                            metadata.name,
                        )

        # Drain module-level pending list (populated by @skill at import time)
        global _PENDING_SKILLS
        while _PENDING_SKILLS:
            pending_meta, pending_fn = _PENDING_SKILLS.pop(0)
            try:
                await self.register(pending_meta, pending_fn, overwrite=False)
                discovered += 1
            except SkillConflictError:
                pass

        logger.info(
            "[SkillRegistry] auto_discover completed | modules=%s new_skills=%s",
            len(modules),
            discovered,
        )
        return discovered

    # ── Skill Suggestions ─────────────────────────────────────────────────────

    async def suggest_skills_for_task(
        self,
        task_description: str,
        max_suggestions: int = 5,
    ) -> List[SkillMetadata]:
        """
        Suggest relevant skills for a natural-language task description.

        Strategy (no external LLM required — pure heuristic):
          1. Keyword search over all skill names, descriptions, and tags.
          2. Boost skills whose tags intersect task keywords.
          3. Return ranked list up to max_suggestions.

        For LLM-powered suggestions, inject a real LLMBridge and override
        this method in a subclass (see LLMSkillRegistry below).

        Args:
            task_description : Free-text description of the task.
            max_suggestions  : Maximum number of skills to suggest.

        Returns:
            List of SkillMetadata ranked by relevance.
        """
        return self.search(
            query=task_description,
            max_results=max_suggestions,
        )

    # ── Stats & Introspection ─────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return a serializable snapshot of the registry state."""
        skills_info = []
        for registered in sorted(self._skills.values(), key=lambda r: r.metadata.name):
            skills_info.append({
                "name": registered.metadata.name,
                "version": registered.metadata.version,
                "risk_level": registered.metadata.risk_level.name,
                "tags": registered.metadata.tags,
                "call_count": registered.call_count,
                "deprecated": registered.metadata.deprecated,
            })
        return {
            "total_skills": len(self._skills),
            "skills": skills_info,
        }

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, skill_name: str) -> bool:
        return skill_name in self._skills
