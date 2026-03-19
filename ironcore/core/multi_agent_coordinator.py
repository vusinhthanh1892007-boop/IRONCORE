"""
IronCore: Multi-Agent Coordinator — Orchestrating Multiple AI Agents
=====================================================================
Phase 8 — The Brain (Claude Sonnet 4.6)

Responsibilities:
  - Decompose a complex user task into discrete, routable SubTasks
  - Maintain an AgentRegistry mapping each AgentType to its capabilities
  - Assign SubTasks to the correct agent based on capability match
  - Execute independent subtasks in parallel (asyncio.gather)
  - Wait for dependency-ordered subtasks before dispatching dependents
  - Detect and resolve result conflicts via LLM adjudication or majority vote
  - Publish granular progress events to EventBus for observability
  - Aggregate all SubTaskResults into a final CoordinationResult

Agent Roles:
  ARCHITECT (GPT-5.4)  — CODE_GENERATION, SECURITY_ANALYSIS, API_SERVER
  BRAIN     (Claude)   — MEMORY_QUERY, REASONING, CONTEXT_OPTIMIZATION
  GHOST     (Gemini)   — WEB_BROWSING, CAPTCHA_SOLVING, SCREENSHOT_ANALYSIS

Integration points:
  - IronCoreEngine (GPT-5.4): EventBus.publish()  ← coordinator events
  - LLMBridge (Brain Phase 1): decompose_task(), resolve_conflict() calls
  - SkillRegistry (Brain Phase 6): suggest_skills_for_task()
  - SessionStore (Brain Phase 5): persist SubTask results per session
  - ContextOptimizer (Brain Phase 7): optimize per-agent context

Author: The Brain (IronCore Project) — Claude Sonnet 4.6
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Awaitable

from pydantic import BaseModel, Field, field_validator, model_validator

from ironcore.core.engine import Action, Event, EventBus, RiskLevel

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Exception Hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class CoordinatorError(Exception):
    """Base exception for all MultiAgentCoordinator errors."""


class AgentNotRegisteredError(CoordinatorError):
    """Raised when delegation is attempted to an unregistered agent."""


class TaskDecompositionError(CoordinatorError):
    """Raised when LLM-based task decomposition fails."""


class SubTaskExecutionError(CoordinatorError):
    """Raised when a subtask fails and has no recovery path."""


class ConflictResolutionError(CoordinatorError):
    """Raised when two contradicting results cannot be resolved."""


class CircularDependencyError(CoordinatorError):
    """Raised when subtask dependency graph contains a cycle."""


# ──────────────────────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────────────────────


class AgentType(str, Enum):
    """
    The three agent personas that compose the IronCore multi-agent system.

    ARCHITECT — GPT-5.4   : code generation, security audits, API engineering
    BRAIN     — Claude 4.6: memory retrieval, long-context reasoning, routing
    GHOST     — Gemini 3.1: web automation, captcha bypass, visual analysis
    """

    ARCHITECT = "architect"
    BRAIN = "brain"
    GHOST = "ghost"


class AgentCapability(str, Enum):
    """
    Atomic capability labels used to route SubTasks to the right agent.

    Each AgentType advertises a fixed set of these, defined in
    AGENT_CAPABILITIES below.
    """

    CODE_GENERATION = "code_generation"
    SECURITY_ANALYSIS = "security_analysis"
    API_SERVER = "api_server"
    MEMORY_QUERY = "memory_query"
    REASONING = "reasoning"
    CONTEXT_OPTIMIZATION = "context_optimization"
    WEB_BROWSING = "web_browsing"
    CAPTCHA_SOLVING = "captcha_solving"
    SCREENSHOT_ANALYSIS = "screenshot_analysis"


class SubTaskStatus(str, Enum):
    """Lifecycle of a single subtask inside a coordination run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"          # dependency failed → skip downstream


# ──────────────────────────────────────────────────────────────────────────────
# Agent Capability Map
# ──────────────────────────────────────────────────────────────────────────────

#: Authoritative mapping: which agent can handle which capabilities.
AGENT_CAPABILITIES: Dict[AgentType, Set[AgentCapability]] = {
    AgentType.ARCHITECT: {
        AgentCapability.CODE_GENERATION,
        AgentCapability.SECURITY_ANALYSIS,
        AgentCapability.API_SERVER,
    },
    AgentType.BRAIN: {
        AgentCapability.MEMORY_QUERY,
        AgentCapability.REASONING,
        AgentCapability.CONTEXT_OPTIMIZATION,
    },
    AgentType.GHOST: {
        AgentCapability.WEB_BROWSING,
        AgentCapability.CAPTCHA_SOLVING,
        AgentCapability.SCREENSHOT_ANALYSIS,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Data Models (Pydantic V2)
# ──────────────────────────────────────────────────────────────────────────────


class SubTask(BaseModel):
    """
    Atomic unit of work inside a multi-agent coordination run.

    Attributes:
        id              : UUID for tracing.
        description     : Natural-language task description sent to the agent.
        required_capability: Which capability is needed (determines routing).
        assigned_agent  : Resolved at routing time; None until assigned.
        depends_on      : IDs of SubTasks whose results must be available first.
        priority        : Higher priority tasks are dispatched first (lower = earlier).
        timeout_seconds : Hard deadline for this subtask.
        metadata        : Arbitrary key-value bag for passing structured hints.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    required_capability: AgentCapability
    assigned_agent: Optional[AgentType] = None
    depends_on: List[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=10)
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("SubTask description cannot be empty.")
        return normalized


class SubTaskResult(BaseModel):
    """
    The outcome of executing one SubTask.

    Attributes:
        subtask_id      : Reference back to the originating SubTask.
        agent_type      : Which agent produced this result.
        status          : Final life-cycle state.
        output          : Free-form result payload (string, dict, list, …).
        error           : Human-readable error description if status==FAILED.
        execution_time_ms: Wall-clock time the agent took to respond.
        confidence      : 0–1 score; used during conflict resolution.
    """

    subtask_id: str
    agent_type: AgentType
    status: SubTaskStatus
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CoordinationResult(BaseModel):
    """
    Top-level output of one complete multi-agent coordination run.

    Attributes:
        task            : The original complex task description.
        session_id      : If provided, correlates results to a SessionStore session.
        subtask_results : All SubTaskResult objects in completion order.
        aggregated_output: Final synthesised answer (assembled by coordinator).
        total_time_ms   : Wall-clock time for the full coordination.
        conflicts_resolved: Number of result contradictions that were adjudicated.
        failed_subtasks : Count of subtasks that ended in FAILED/SKIPPED status.
    """

    task: str
    session_id: Optional[str] = None
    subtask_results: List[SubTaskResult] = Field(default_factory=list)
    aggregated_output: str = ""
    total_time_ms: float = Field(default=0.0, ge=0.0)
    conflicts_resolved: int = Field(default=0, ge=0)
    failed_subtasks: int = Field(default=0, ge=0)

    @property
    def success(self) -> bool:
        """True if every subtask completed without failure."""
        return self.failed_subtasks == 0


class AgentRegistration(BaseModel):
    """Runtime record of one registered agent instance."""

    agent_type: AgentType
    capabilities: Set[AgentCapability]
    #: Async callable that takes (subtask: SubTask, context: Dict) → SubTaskResult.
    handler: Any  # Callable[[SubTask, Dict], Awaitable[SubTaskResult]]
    is_available: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


# ──────────────────────────────────────────────────────────────────────────────
# Dependency Resolver
# ──────────────────────────────────────────────────────────────────────────────


class DependencyResolver:
    """
    Topological sort of subtasks respecting depends_on relationships.

    Raises CircularDependencyError if a cycle is detected.
    Returns execution waves: each inner list may be dispatched in parallel.
    """

    @staticmethod
    def resolve(subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        Kahn's algorithm — produces BFS-ordered execution waves.

        Wave 0  → no dependencies (can run immediately in parallel)
        Wave 1  → depends only on wave 0 tasks
        …

        Returns:
            List of waves; each wave is a list of SubTask objects
            that may execute concurrently.
        """
        id_map: Dict[str, SubTask] = {st.id: st for st in subtasks}
        in_degree: Dict[str, int] = {st.id: 0 for st in subtasks}
        dependents: Dict[str, List[str]] = {st.id: [] for st in subtasks}

        for st in subtasks:
            for dep_id in st.depends_on:
                if dep_id not in id_map:
                    raise CoordinatorError(
                        f"SubTask '{st.id}' depends on unknown subtask '{dep_id}'."
                    )
                in_degree[st.id] += 1
                dependents[dep_id].append(st.id)

        # Initial wave: tasks with in_degree == 0, sorted by priority asc
        wave_queue: List[str] = sorted(
            [sid for sid, deg in in_degree.items() if deg == 0],
            key=lambda sid: id_map[sid].priority,
        )

        waves: List[List[SubTask]] = []
        processed = 0

        while wave_queue:
            current_wave = [id_map[sid] for sid in wave_queue]
            waves.append(current_wave)
            processed += len(wave_queue)
            next_wave: List[str] = []

            for sid in wave_queue:
                for dependent_id in dependents[sid]:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        next_wave.append(dependent_id)

            wave_queue = sorted(next_wave, key=lambda s: id_map[s].priority)

        if processed != len(subtasks):
            raise CircularDependencyError(
                f"Circular dependency detected among subtasks. "
                f"Processed {processed}/{len(subtasks)} nodes."
            )

        return waves


# ──────────────────────────────────────────────────────────────────────────────
# LLM-based Task Decomposer
# ──────────────────────────────────────────────────────────────────────────────


class TaskDecomposer:
    """
    Uses an optional LLM callable to break a complex task into SubTasks.

    When no LLM callable is provided (testing / offline mode), a simple
    heuristic decomposition is used instead.
    """

    # Capabilities ordered by keyword hints
    _KEYWORD_CAPABILITY_MAP: List[tuple[list[str], AgentCapability]] = [
        (["browse", "web", "scrape", "url", "http", "website", "crawl"],
         AgentCapability.WEB_BROWSING),
        (["captcha", "bypass", "recaptcha", "geetest"],
         AgentCapability.CAPTCHA_SOLVING),
        (["screenshot", "image", "visual", "vision"],
         AgentCapability.SCREENSHOT_ANALYSIS),
        (["code", "generate", "write", "implement", "function", "class", "fix bug"],
         AgentCapability.CODE_GENERATION),
        (["security", "audit", "vulnerability", "cve", "pentest", "rbac"],
         AgentCapability.SECURITY_ANALYSIS),
        (["api", "server", "endpoint", "rest", "route"],
         AgentCapability.API_SERVER),
        (["remember", "memory", "recall", "query", "graph", "know", "history"],
         AgentCapability.MEMORY_QUERY),
        (["reason", "think", "analyse", "analyze", "explain", "summarize", "plan"],
         AgentCapability.REASONING),
        (["context", "token", "optimize", "budget", "compress"],
         AgentCapability.CONTEXT_OPTIMIZATION),
    ]

    def __init__(
        self,
        llm_callable: Optional[Callable[..., Awaitable[str]]] = None,
    ) -> None:
        self._llm = llm_callable

    async def decompose(self, complex_task: str) -> List[SubTask]:
        """
        Split `complex_task` into a list of SubTask objects.

        Priority 1: If an LLM callable is provided, invoke it with a structured
                    decomposition prompt and parse its JSON output.
        Priority 2: Heuristic keyword-based decomposition.
        """
        if self._llm is not None:
            try:
                return await self._llm_decompose(complex_task)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[Coordinator/Decomposer] LLM decomposition failed (%s); "
                    "falling back to heuristic.",
                    exc,
                )

        return self._heuristic_decompose(complex_task)

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    async def _llm_decompose(self, task: str) -> List[SubTask]:
        """
        Ask an LLM to produce a JSON array of subtask objects.

        Expected LLM output format (strict JSON):
        [
          {
            "description": "Search web for pricing data",
            "required_capability": "web_browsing",
            "depends_on": [],
            "priority": 3
          },
          ...
        ]
        """
        import json as _json  # local import — avoids top-level circular deps

        prompt = _DECOMPOSITION_PROMPT_TEMPLATE.format(task=task)
        raw = await self._llm(prompt)  # type: ignore[misc]

        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

        try:
            items = _json.loads(raw)
        except _json.JSONDecodeError as exc:
            raise TaskDecompositionError(
                f"LLM returned invalid JSON during decomposition: {exc}\nRaw: {raw[:300]}"
            ) from exc

        if not isinstance(items, list):
            raise TaskDecompositionError(
                f"Expected JSON array from LLM, got {type(items).__name__}."
            )

        subtasks: List[SubTask] = []
        for item in items:
            cap_str = item.get("required_capability", "reasoning")
            try:
                cap = AgentCapability(cap_str)
            except ValueError:
                logger.warning(
                    "[Coordinator/Decomposer] Unknown capability '%s'; defaulting to REASONING.",
                    cap_str,
                )
                cap = AgentCapability.REASONING

            subtasks.append(
                SubTask(
                    description=item.get("description", task),
                    required_capability=cap,
                    depends_on=item.get("depends_on", []),
                    priority=int(item.get("priority", 5)),
                    metadata=item.get("metadata", {}),
                )
            )

        if not subtasks:
            raise TaskDecompositionError("LLM returned empty subtask list.")

        return subtasks

    # ------------------------------------------------------------------
    # Heuristic path
    # ------------------------------------------------------------------

    def _heuristic_decompose(self, task: str) -> List[SubTask]:
        """
        Keyword matching: one SubTask per detected capability, plus a
        REASONING subtask that depends on all others to aggregate results.
        """
        task_lower = task.lower()
        detected: List[AgentCapability] = []

        for keywords, cap in self._KEYWORD_CAPABILITY_MAP:
            if any(kw in task_lower for kw in keywords) and cap not in detected:
                detected.append(cap)

        # Always include at least a reasoning pass
        if not detected:
            detected = [AgentCapability.REASONING]

        # Build sub-tasks; last one aggregates (depends on all prior)
        subtasks: List[SubTask] = []
        for i, cap in enumerate(detected[:-1]):
            subtasks.append(
                SubTask(
                    description=f"[Heuristic] {cap.value.replace('_', ' ').title()} step for: {task}",
                    required_capability=cap,
                    priority=i + 1,
                )
            )

        final_cap = detected[-1]
        final = SubTask(
            description=f"[Heuristic] Aggregate and reason about results for: {task}",
            required_capability=final_cap,
            depends_on=[st.id for st in subtasks],
            priority=len(detected),
        )
        subtasks.append(final)
        return subtasks


_DECOMPOSITION_PROMPT_TEMPLATE = """\
You are an orchestrator for a multi-agent system.
Break the following complex task into discrete subtasks that can be routed to specialist agents.

Available capabilities (use EXACTLY these values):
  code_generation, security_analysis, api_server,
  memory_query, reasoning, context_optimization,
  web_browsing, captcha_solving, screenshot_analysis

Task: {task}

Output a JSON array where each element has:
  "description"         : string  — what the agent must do
  "required_capability" : string  — one capability from the list above
  "depends_on"          : array   — IDs of subtasks this one depends on (use "" if none yet)
  "priority"            : int     — 1 (highest) … 10 (lowest)

Rules:
- Minimise the number of subtasks; merge if same capability needed.
- If a subtask needs results from another: list its ID in depends_on (forward references OK).
- Return ONLY the JSON array, no markdown.
"""


# ──────────────────────────────────────────────────────────────────────────────
# Conflict Resolver
# ──────────────────────────────────────────────────────────────────────────────


class ConflictResolver:
    """
    Adjudicates contradicting SubTaskResults via two strategies:

    1. Confidence-weighted: pick result with highest `confidence` score.
    2. LLM adjudication: if scores are close (< 0.1 difference) and an LLM
       callable is available, ask the LLM to choose the more accurate answer.
    """

    _CLOSE_CONFIDENCE_THRESHOLD = 0.1

    def __init__(
        self,
        llm_callable: Optional[Callable[..., Awaitable[str]]] = None,
    ) -> None:
        self._llm = llm_callable

    async def resolve(self, results: List[SubTaskResult]) -> SubTaskResult:
        """
        Resolve a list of contradicting results for the SAME subtask.

        Returns the single SubTaskResult that should be used downstream.
        Raises ConflictResolutionError if resolution is impossible.
        """
        if not results:
            raise ConflictResolutionError("No results provided to conflict resolver.")
        if len(results) == 1:
            return results[0]

        # Sort descending by confidence
        ranked = sorted(results, key=lambda r: r.confidence, reverse=True)
        top, runner_up = ranked[0], ranked[1]
        delta = top.confidence - runner_up.confidence

        if delta > self._CLOSE_CONFIDENCE_THRESHOLD:
            logger.info(
                "[Coordinator/Conflict] Resolved by confidence: agent=%s (%.2f vs %.2f)",
                top.agent_type.value,
                top.confidence,
                runner_up.confidence,
            )
            return top

        if self._llm is not None:
            return await self._llm_adjudicate(ranked)

        # Final tie-break: prefer BRAIN > ARCHITECT > GHOST
        preference = [AgentType.BRAIN, AgentType.ARCHITECT, AgentType.GHOST]
        for preferred in preference:
            for r in ranked:
                if r.agent_type == preferred:
                    logger.info(
                        "[Coordinator/Conflict] Resolved by agent preference: agent=%s",
                        r.agent_type.value,
                    )
                    return r

        return ranked[0]

    async def _llm_adjudicate(self, ranked: List[SubTaskResult]) -> SubTaskResult:
        """Ask LLM to pick the best result from a serialised summary."""
        import json as _json

        options = [
            {
                "index": i,
                "agent": r.agent_type.value,
                "output": str(r.output)[:500],
                "confidence": r.confidence,
            }
            for i, r in enumerate(ranked)
        ]
        prompt = (
            "Two agents produced different results for the same task.\n"
            f"Options: {_json.dumps(options)}\n"
            "Which index (0-based integer) is more accurate? Reply with the integer only."
        )
        try:
            raw = await self._llm(prompt)  # type: ignore[misc]
            idx = int(raw.strip())
            if 0 <= idx < len(ranked):
                logger.info(
                    "[Coordinator/Conflict] LLM adjudication chose index %d (agent=%s)",
                    idx,
                    ranked[idx].agent_type.value,
                )
                return ranked[idx]
        except (ValueError, TypeError) as exc:
            logger.warning("[Coordinator/Conflict] LLM adjudication failed: %s", exc)

        return ranked[0]


# ──────────────────────────────────────────────────────────────────────────────
# Default Agent Handlers (stubs — replaced by real agent instances in production)
# ──────────────────────────────────────────────────────────────────────────────


async def _stub_handler(subtask: SubTask, context: Dict[str, Any]) -> SubTaskResult:
    """
    Default no-op handler used when a real agent is not yet connected.

    Returns a SubTaskResult indicating the agent is unavailable.
    """
    logger.debug(
        "[Coordinator] Stub handler called for subtask=%s capability=%s",
        subtask.id,
        subtask.required_capability.value,
    )
    return SubTaskResult(
        subtask_id=subtask.id,
        agent_type=AgentType.BRAIN,  # Brain is the coordinator itself
        status=SubTaskStatus.COMPLETED,
        output=f"[Stub] No real handler registered for capability "
               f"'{subtask.required_capability.value}'. "
               f"Task: {subtask.description[:100]}",
        confidence=0.3,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main Coordinator
# ──────────────────────────────────────────────────────────────────────────────


class MultiAgentCoordinator:
    """
    Orchestrates ARCHITECT, BRAIN, and GHOST agents to solve complex tasks.

    Lifecycle of coordinate():
      1. Decompose task → SubTasks  (LLM or heuristic)
      2. Validate dependency graph  (Kahn's topo-sort)
      3. Assign each SubTask to an agent based on capability
      4. Execute SubTasks wave-by-wave; each wave runs in parallel
      5. Detect conflicts when >1 agent produces results for the same subtask
      6. Resolve conflicts via confidence scoring or LLM adjudication
      7. Assemble CoordinationResult with full audit statistics

    EventBus events published:
      "coordinator.task_received"    — when coordinate() is called
      "coordinator.task_decomposed"  — after successful decomposition
      "coordinator.subtask_started"  — before each subtask execution
      "coordinator.subtask_completed"— after successful subtask
      "coordinator.subtask_failed"   — after failed subtask
      "coordinator.conflict_detected"— when contradicting results found
      "coordinator.task_completed"   — final result assembled
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        llm_callable: Optional[Callable[..., Awaitable[str]]] = None,
    ) -> None:
        """
        Args:
            event_bus   : IronCoreEngine's EventBus for progress notifications.
                          If None, events are still logged but not published.
            llm_callable: Async callable (prompt: str) -> str used for task
                          decomposition and conflict resolution.
                          If None, heuristic + confidence-based fallbacks are used.
        """
        self._bus = event_bus
        self._decomposer = TaskDecomposer(llm_callable=llm_callable)
        self._conflict_resolver = ConflictResolver(llm_callable=llm_callable)
        self._registry: Dict[AgentType, AgentRegistration] = {}

        # Register default stub handlers for all three agent types
        for agent_type, caps in AGENT_CAPABILITIES.items():
            self._registry[agent_type] = AgentRegistration(
                agent_type=agent_type,
                capabilities=caps,
                handler=_stub_handler,
            )

        logger.info("[Coordinator] Initialized with %d stub agent(s).", len(self._registry))

    # ------------------------------------------------------------------
    # Agent Registration
    # ------------------------------------------------------------------

    def register_agent(
        self,
        agent_type: AgentType,
        handler: Callable[..., Awaitable[SubTaskResult]],
        extra_capabilities: Optional[Set[AgentCapability]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a real agent handler, replacing the default stub.

        Args:
            agent_type        : One of ARCHITECT / BRAIN / GHOST.
            handler           : Async callable (subtask, context) → SubTaskResult.
            extra_capabilities: Additional capabilities beyond the defaults.
            metadata          : Arbitrary metadata stored alongside the registration.
        """
        caps = AGENT_CAPABILITIES[agent_type].copy()
        if extra_capabilities:
            caps |= extra_capabilities

        self._registry[agent_type] = AgentRegistration(
            agent_type=agent_type,
            capabilities=caps,
            handler=handler,
            metadata=metadata or {},
        )
        logger.info(
            "[Coordinator] Registered agent type=%s caps=%s",
            agent_type.value,
            {c.value for c in caps},
        )

    def set_available(self, agent_type: AgentType, available: bool) -> None:
        """Mark an agent as available or temporarily unavailable."""
        if agent_type not in self._registry:
            raise AgentNotRegisteredError(f"Agent '{agent_type.value}' not registered.")
        self._registry[agent_type].is_available = available
        logger.info(
            "[Coordinator] Agent %s availability → %s",
            agent_type.value,
            available,
        )

    # ------------------------------------------------------------------
    # Core Coordination
    # ------------------------------------------------------------------

    async def coordinate(
        self,
        task: str,
        session_id: Optional[str] = None,
    ) -> CoordinationResult:
        """
        Full multi-agent coordination pipeline for `task`.

        Args:
            task       : The complex user task description.
            session_id : Optional session ID for event correlation.

        Returns:
            CoordinationResult with all subtask results and aggregated output.
        """
        start_ts = time.monotonic()
        task_id = str(uuid.uuid4())

        await self._publish(
            "coordinator.task_received",
            {"task_id": task_id, "task": task[:200], "session_id": session_id},
        )
        logger.info("[Coordinator] Task received task_id=%s", task_id)

        # ── Step 1: Decompose ──────────────────────────────────────────
        try:
            subtasks = await self._decomposer.decompose(task)
        except TaskDecompositionError as exc:
            logger.error("[Coordinator] Decomposition failed: %s", exc)
            return CoordinationResult(
                task=task,
                session_id=session_id,
                aggregated_output=f"[Coordinator] Task decomposition failed: {exc}",
                failed_subtasks=1,
                total_time_ms=(time.monotonic() - start_ts) * 1000,
            )

        logger.info(
            "[Coordinator] Task decomposed into %d subtask(s).",
            len(subtasks),
        )
        await self._publish(
            "coordinator.task_decomposed",
            {
                "task_id": task_id,
                "subtask_count": len(subtasks),
                "subtask_ids": [st.id for st in subtasks],
            },
        )

        # ── Step 2: Topological Sort ───────────────────────────────────
        try:
            waves = DependencyResolver.resolve(subtasks)
        except (CircularDependencyError, CoordinatorError) as exc:
            logger.error("[Coordinator] Dependency resolution failed: %s", exc)
            return CoordinationResult(
                task=task,
                session_id=session_id,
                aggregated_output=f"[Coordinator] Dependency error: {exc}",
                failed_subtasks=len(subtasks),
                total_time_ms=(time.monotonic() - start_ts) * 1000,
            )

        # ── Step 3: Route subtasks → agents ───────────────────────────
        self._assign_agents(subtasks)

        # ── Step 4 + 5 + 6: Execute waves, collect, resolve conflicts ──
        all_results: List[SubTaskResult] = []
        completed_results: Dict[str, SubTaskResult] = {}
        failed_count = 0
        conflict_count = 0

        for wave_idx, wave in enumerate(waves):
            logger.debug(
                "[Coordinator] Executing wave %d with %d subtask(s).",
                wave_idx,
                len(wave),
            )
            # Skip subtasks whose dependencies failed
            executable = [
                st for st in wave
                if not any(
                    completed_results.get(dep_id, SubTaskResult(
                        subtask_id=dep_id,
                        agent_type=AgentType.BRAIN,
                        status=SubTaskStatus.FAILED,
                    )).status == SubTaskStatus.FAILED
                    for dep_id in st.depends_on
                )
            ]
            skipped = [st for st in wave if st not in executable]

            for st in skipped:
                skip_result = SubTaskResult(
                    subtask_id=st.id,
                    agent_type=st.assigned_agent or AgentType.BRAIN,
                    status=SubTaskStatus.SKIPPED,
                    output="Skipped due to failed dependency.",
                    confidence=0.0,
                )
                all_results.append(skip_result)
                completed_results[st.id] = skip_result
                failed_count += 1

            if not executable:
                continue

            # Build context for each subtask (inject dependency outputs)
            contexts = {
                st.id: {
                    "task_id": task_id,
                    "session_id": session_id,
                    "dependency_outputs": {
                        dep_id: completed_results[dep_id].output
                        for dep_id in st.depends_on
                        if dep_id in completed_results
                    },
                }
                for st in executable
            }

            # Execute this wave in parallel
            wave_results = await asyncio.gather(
                *[self._execute_subtask(st, contexts[st.id]) for st in executable],
                return_exceptions=True,
            )

            for st, result in zip(executable, wave_results):
                if isinstance(result, BaseException):
                    err_result = SubTaskResult(
                        subtask_id=st.id,
                        agent_type=st.assigned_agent or AgentType.BRAIN,
                        status=SubTaskStatus.FAILED,
                        error=str(result),
                        confidence=0.0,
                    )
                    all_results.append(err_result)
                    completed_results[st.id] = err_result
                    failed_count += 1
                    await self._publish(
                        "coordinator.subtask_failed",
                        {"task_id": task_id, "subtask_id": st.id, "error": str(result)},
                    )
                else:
                    all_results.append(result)  # type: ignore[arg-type]
                    completed_results[st.id] = result  # type: ignore[index]
                    if result.status == SubTaskStatus.FAILED:  # type: ignore[union-attr]
                        failed_count += 1

        # ── Step 7: Detect and resolve conflicts ───────────────────────
        conflict_count, all_results = await self._detect_and_resolve_conflicts(
            all_results
        )

        # ── Step 8: Aggregate output ───────────────────────────────────
        aggregated = self._aggregate_outputs(task, all_results)

        elapsed_ms = (time.monotonic() - start_ts) * 1000
        coord_result = CoordinationResult(
            task=task,
            session_id=session_id,
            subtask_results=all_results,
            aggregated_output=aggregated,
            total_time_ms=elapsed_ms,
            conflicts_resolved=conflict_count,
            failed_subtasks=failed_count,
        )

        await self._publish(
            "coordinator.task_completed",
            {
                "task_id": task_id,
                "subtask_count": len(all_results),
                "failed": failed_count,
                "conflicts_resolved": conflict_count,
                "elapsed_ms": elapsed_ms,
            },
        )
        logger.info(
            "[Coordinator] Task completed task_id=%s subtasks=%d failed=%d elapsed_ms=%.1f",
            task_id,
            len(all_results),
            failed_count,
            elapsed_ms,
        )
        return coord_result

    # ------------------------------------------------------------------
    # Delegation helper
    # ------------------------------------------------------------------

    async def delegate_to_agent(
        self,
        agent_type: AgentType,
        subtask: SubTask,
        context: Optional[Dict[str, Any]] = None,
    ) -> SubTaskResult:
        """
        Directly delegate a single SubTask to a specific agent.

        Useful for callers who want to bypass the full coordination pipeline
        (e.g., interactive single-agent tests, debugging).
        """
        if agent_type not in self._registry:
            raise AgentNotRegisteredError(
                f"Agent '{agent_type.value}' is not registered."
            )
        reg = self._registry[agent_type]
        if not reg.is_available:
            raise AgentNotRegisteredError(
                f"Agent '{agent_type.value}' is currently unavailable."
            )
        subtask.assigned_agent = agent_type
        return await reg.handler(subtask, context or {})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assign_agents(self, subtasks: List[SubTask]) -> None:
        """
        Set assigned_agent on every SubTask based on capability routing.

        Priority: first available agent whose capability set contains the
        required capability; falls back to BRAIN if none found.
        """
        for st in subtasks:
            assigned: Optional[AgentType] = None
            for agent_type, reg in self._registry.items():
                if reg.is_available and st.required_capability in reg.capabilities:
                    assigned = agent_type
                    break
            if assigned is None:
                logger.warning(
                    "[Coordinator] No agent found for capability '%s'; routing to BRAIN.",
                    st.required_capability.value,
                )
                assigned = AgentType.BRAIN
            st.assigned_agent = assigned

    async def _execute_subtask(
        self,
        subtask: SubTask,
        context: Dict[str, Any],
    ) -> SubTaskResult:
        """
        Execute one SubTask via its assigned agent handler with a timeout.

        Publishes subtask_started before execution and subtask_completed after.
        """
        agent_type = subtask.assigned_agent or AgentType.BRAIN
        reg = self._registry.get(agent_type)
        if reg is None or not reg.is_available:
            raise AgentNotRegisteredError(
                f"Agent '{agent_type.value}' unavailable for subtask '{subtask.id}'."
            )

        await self._publish(
            "coordinator.subtask_started",
            {
                "subtask_id": subtask.id,
                "agent": agent_type.value,
                "capability": subtask.required_capability.value,
            },
        )
        logger.debug(
            "[Coordinator] Executing subtask=%s agent=%s",
            subtask.id,
            agent_type.value,
        )

        t0 = time.monotonic()
        try:
            result: SubTaskResult = await asyncio.wait_for(
                reg.handler(subtask, context),
                timeout=subtask.timeout_seconds,
            )
            result = result.model_copy(
                update={"execution_time_ms": (time.monotonic() - t0) * 1000}
            )
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "[Coordinator] Subtask=%s timed out after %.1fms",
                subtask.id,
                elapsed,
            )
            result = SubTaskResult(
                subtask_id=subtask.id,
                agent_type=agent_type,
                status=SubTaskStatus.FAILED,
                error=f"Timeout after {subtask.timeout_seconds}s",
                execution_time_ms=elapsed,
                confidence=0.0,
            )

        await self._publish(
            "coordinator.subtask_completed",
            {
                "subtask_id": subtask.id,
                "agent": agent_type.value,
                "status": result.status.value,
                "elapsed_ms": result.execution_time_ms,
            },
        )
        return result

    async def _detect_and_resolve_conflicts(
        self,
        results: List[SubTaskResult],
    ) -> tuple[int, List[SubTaskResult]]:
        """
        Find subtasks where >1 result exists (e.g. from parallel agents),
        resolve conflicts, return (conflict_count, deduplicated_results).
        """
        from collections import defaultdict

        by_subtask: Dict[str, List[SubTaskResult]] = defaultdict(list)
        for r in results:
            by_subtask[r.subtask_id].append(r)

        resolved: List[SubTaskResult] = []
        conflict_count = 0

        for subtask_id, bucket in by_subtask.items():
            if len(bucket) == 1:
                resolved.append(bucket[0])
                continue

            # Multiple results → potential conflict
            successful = [r for r in bucket if r.status == SubTaskStatus.COMPLETED]
            if len(successful) <= 1:
                resolved.append(bucket[0])
                continue

            conflict_count += 1
            await self._publish(
                "coordinator.conflict_detected",
                {
                    "subtask_id": subtask_id,
                    "competing_agents": [r.agent_type.value for r in successful],
                },
            )
            winner = await self._conflict_resolver.resolve(successful)
            resolved.append(winner)

        return conflict_count, resolved

    @staticmethod
    def _aggregate_outputs(task: str, results: List[SubTaskResult]) -> str:
        """
        Combine all successful SubTaskResult outputs into a readable summary.

        This is a lightweight in-process aggregation.  In production the
        coordinator would route this step through LLMBridge for semantic merging.
        """
        completed = [r for r in results if r.status == SubTaskStatus.COMPLETED]
        if not completed:
            failed = [r for r in results if r.status == SubTaskStatus.FAILED]
            return (
                f"[Coordinator] All {len(failed)} subtask(s) failed. "
                f"Task: {task[:100]}"
            )

        lines: List[str] = [f"[Task] {task}", ""]
        for r in completed:
            lines.append(f"[{r.agent_type.value.upper()}] {str(r.output)[:300]}")

        lines.append(
            f"\n[Summary] {len(completed)}/{len(results)} subtask(s) succeeded."
        )
        return "\n".join(lines)

    async def _publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Safely publish an event to the bus; swallow all errors."""
        if self._bus is None:
            logger.debug("[Coordinator] (no bus) Event: %s %s", event_type, payload)
            return
        try:
            event = Event(event_type=event_type, payload=payload)
            await self._bus.publish(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Coordinator] Failed to publish event '%s': %s", event_type, exc
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_agents(self) -> List[Dict[str, Any]]:
        """Return a summary of all registered agents and their capabilities."""
        return [
            {
                "agent_type": reg.agent_type.value,
                "capabilities": sorted(c.value for c in reg.capabilities),
                "is_available": reg.is_available,
                "metadata": reg.metadata,
            }
            for reg in self._registry.values()
        ]

    def capable_agents(self, capability: AgentCapability) -> List[AgentType]:
        """Return all agents that support the given capability (available only)."""
        return [
            reg.agent_type
            for reg in self._registry.values()
            if reg.is_available and capability in reg.capabilities
        ]
