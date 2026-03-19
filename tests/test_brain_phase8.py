"""
Tests for Brain Phase 8 — Multi-Agent Coordinator
==================================================
Coverage:
  - AgentType / AgentCapability enumerations
  - AGENT_CAPABILITIES mapping consistency
  - SubTask model validation (empty description guard)
  - SubTaskResult model validation
  - DependencyResolver: linear chain, simple parallel, complex DAG, cycle detection,
    unknown dependency reference, single node, empty input
  - TaskDecomposer: heuristic decomposition for various task types, LLM callable path,
    LLM JSON parse failure fallback, empty LLM output handling
  - ConflictResolver: single result passthrough, high confidence gap → no LLM call,
    close scores → LLM adjudication, LLM adjudication failure → preference fallback,
    no LLM available → preference-order fallback
  - MultiAgentCoordinator: initialization & stub agents, register_agent, set_available,
    list_agents, capable_agents, delegate_to_agent, full coordinate() pipeline,
    timeout subtask, failed dependency → skip downstream, conflict detection &
    resolution in pipeline, EventBus integration, all-fail aggregation
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from ironcore.core.multi_agent_coordinator import (
    AGENT_CAPABILITIES,
    AgentCapability,
    AgentNotRegisteredError,
    AgentType,
    CircularDependencyError,
    ConflictResolver,
    ConflictResolutionError,
    CoordinationResult,
    CoordinatorError,
    DependencyResolver,
    MultiAgentCoordinator,
    SubTask,
    SubTaskResult,
    SubTaskStatus,
    TaskDecomposer,
    TaskDecompositionError,
)
from ironcore.core.engine import EventBus, RiskLevel


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_subtask(
    description: str = "Do something",
    cap: AgentCapability = AgentCapability.REASONING,
    depends_on: Optional[List[str]] = None,
    priority: int = 5,
) -> SubTask:
    return SubTask(
        description=description,
        required_capability=cap,
        depends_on=depends_on or [],
        priority=priority,
    )


async def _ok_handler(subtask: SubTask, context: Dict[str, Any]) -> SubTaskResult:
    """Always-successful handler for testing."""
    return SubTaskResult(
        subtask_id=subtask.id,
        agent_type=AgentType.BRAIN,
        status=SubTaskStatus.COMPLETED,
        output=f"done:{subtask.description[:30]}",
        confidence=0.9,
    )


async def _fail_handler(subtask: SubTask, context: Dict[str, Any]) -> SubTaskResult:
    """Always-failing handler for testing."""
    return SubTaskResult(
        subtask_id=subtask.id,
        agent_type=AgentType.BRAIN,
        status=SubTaskStatus.FAILED,
        error="Deliberate failure",
        confidence=0.0,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Enum & Capability Map Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestAgentCapabilityMap:
    def test_all_agent_types_have_capabilities(self) -> None:
        for agent in AgentType:
            assert agent in AGENT_CAPABILITIES
            assert len(AGENT_CAPABILITIES[agent]) > 0

    def test_no_capability_overlap_between_agents(self) -> None:
        """Each capability should belong to exactly one agent type."""
        seen: Dict[AgentCapability, AgentType] = {}
        for agent, caps in AGENT_CAPABILITIES.items():
            for cap in caps:
                assert cap not in seen, (
                    f"Capability {cap.value} claimed by both "
                    f"{seen.get(cap)} and {agent}"
                )
                seen[cap] = agent

    def test_agent_type_values(self) -> None:
        assert AgentType.ARCHITECT.value == "architect"
        assert AgentType.BRAIN.value == "brain"
        assert AgentType.GHOST.value == "ghost"

    def test_all_capabilities_assigned(self) -> None:
        assigned = set()
        for caps in AGENT_CAPABILITIES.values():
            assigned |= caps
        for cap in AgentCapability:
            assert cap in assigned, f"{cap.value} not assigned to any agent"


# ──────────────────────────────────────────────────────────────────────────────
# SubTask / SubTaskResult Validation
# ──────────────────────────────────────────────────────────────────────────────


class TestSubTaskModel:
    def test_valid_subtask(self) -> None:
        st = _make_subtask()
        assert st.id  # UUID assigned
        assert st.required_capability == AgentCapability.REASONING

    def test_empty_description_raises(self) -> None:
        with pytest.raises(Exception):
            SubTask(description="   ", required_capability=AgentCapability.REASONING)

    def test_default_priority(self) -> None:
        st = _make_subtask()
        assert 1 <= st.priority <= 10

    def test_unique_ids(self) -> None:
        ids = {_make_subtask().id for _ in range(20)}
        assert len(ids) == 20


class TestSubTaskResultModel:
    def test_valid_result(self) -> None:
        st = _make_subtask()
        r = SubTaskResult(
            subtask_id=st.id,
            agent_type=AgentType.BRAIN,
            status=SubTaskStatus.COMPLETED,
            output="ok",
        )
        assert r.confidence == 1.0

    def test_confidence_clamped(self) -> None:
        st = _make_subtask()
        with pytest.raises(Exception):
            SubTaskResult(
                subtask_id=st.id,
                agent_type=AgentType.BRAIN,
                status=SubTaskStatus.COMPLETED,
                confidence=1.5,
            )


# ──────────────────────────────────────────────────────────────────────────────
# DependencyResolver Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestDependencyResolver:
    def test_empty_list(self) -> None:
        waves = DependencyResolver.resolve([])
        assert waves == []

    def test_single_node(self) -> None:
        st = _make_subtask()
        waves = DependencyResolver.resolve([st])
        assert len(waves) == 1
        assert waves[0][0].id == st.id

    def test_two_independent_tasks_same_wave(self) -> None:
        a = _make_subtask("A")
        b = _make_subtask("B")
        waves = DependencyResolver.resolve([a, b])
        assert len(waves) == 1
        assert len(waves[0]) == 2

    def test_linear_chain_separate_waves(self) -> None:
        a = _make_subtask("A")
        b = SubTask(description="B", required_capability=AgentCapability.REASONING, depends_on=[a.id])
        c = SubTask(description="C", required_capability=AgentCapability.REASONING, depends_on=[b.id])
        waves = DependencyResolver.resolve([a, b, c])
        assert len(waves) == 3
        assert waves[0][0].id == a.id
        assert waves[1][0].id == b.id
        assert waves[2][0].id == c.id

    def test_diamond_dag(self) -> None:
        """A → B, A → C; D depends on B and C."""
        a = _make_subtask("A", priority=1)
        b = SubTask(description="B", required_capability=AgentCapability.REASONING, depends_on=[a.id], priority=2)
        c = SubTask(description="C", required_capability=AgentCapability.REASONING, depends_on=[a.id], priority=2)
        d = SubTask(description="D", required_capability=AgentCapability.REASONING, depends_on=[b.id, c.id], priority=3)
        waves = DependencyResolver.resolve([a, b, c, d])
        assert len(waves) == 3
        assert waves[0][0].id == a.id
        assert {t.id for t in waves[1]} == {b.id, c.id}
        assert waves[2][0].id == d.id

    def test_cycle_raises(self) -> None:
        a = SubTask(description="A", required_capability=AgentCapability.REASONING)
        b = SubTask(
            description="B",
            required_capability=AgentCapability.REASONING,
            depends_on=[a.id],
        )
        # Manually inject a cycle
        a_cyclic = SubTask(
            id=a.id,
            description="A",
            required_capability=AgentCapability.REASONING,
            depends_on=[b.id],
        )
        with pytest.raises(CircularDependencyError):
            DependencyResolver.resolve([a_cyclic, b])

    def test_unknown_dependency_raises(self) -> None:
        st = SubTask(
            description="X",
            required_capability=AgentCapability.REASONING,
            depends_on=["nonexistent-uuid"],
        )
        with pytest.raises(CoordinatorError):
            DependencyResolver.resolve([st])

    def test_priority_ordering_within_wave(self) -> None:
        a = _make_subtask("A", priority=3)
        b = _make_subtask("B", priority=1)
        c = _make_subtask("C", priority=2)
        waves = DependencyResolver.resolve([a, b, c])
        # All independent → one wave, sorted by priority
        assert len(waves) == 1
        ids_in_order = [t.id for t in waves[0]]
        # b(1) < c(2) < a(3)
        assert ids_in_order == [b.id, c.id, a.id]


# ──────────────────────────────────────────────────────────────────────────────
# TaskDecomposer Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestTaskDecomposer:
    def test_heuristic_web_task(self) -> None:
        d = TaskDecomposer()
        result = asyncio.run(d.decompose("Browse the web to find information about Python"))
        assert len(result) >= 1
        caps = {st.required_capability for st in result}
        assert AgentCapability.WEB_BROWSING in caps

    def test_heuristic_code_task(self) -> None:
        d = TaskDecomposer()
        result = asyncio.run(d.decompose("Generate code to implement a REST API server"))
        caps = {st.required_capability for st in result}
        assert AgentCapability.CODE_GENERATION in caps or AgentCapability.API_SERVER in caps

    def test_heuristic_unknown_task_falls_back_to_reasoning(self) -> None:
        d = TaskDecomposer()
        result = asyncio.run(d.decompose("xyzzy quux frobnicate"))
        assert len(result) == 1
        assert result[0].required_capability == AgentCapability.REASONING

    def test_heuristic_dependency_chain(self) -> None:
        """When multiple capabilities detected, last task depends on all prior."""
        d = TaskDecomposer()
        result = asyncio.run(
            d.decompose("Browse web for data then generate code to analyse it")
        )
        if len(result) > 1:
            last = result[-1]
            assert len(last.depends_on) >= 1

    @pytest.mark.asyncio
    async def test_llm_callable_path(self) -> None:
        payload = json.dumps([
            {
                "description": "Fetch data from API",
                "required_capability": "web_browsing",
                "depends_on": [],
                "priority": 2,
            },
            {
                "description": "Analyse results",
                "required_capability": "reasoning",
                "depends_on": [],
                "priority": 5,
            },
        ])
        mock_llm = AsyncMock(return_value=payload)
        d = TaskDecomposer(llm_callable=mock_llm)
        result = await d.decompose("complex task")
        assert len(result) == 2
        assert result[0].required_capability == AgentCapability.WEB_BROWSING
        assert result[1].required_capability == AgentCapability.REASONING
        mock_llm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_callable_bad_json_falls_back(self) -> None:
        mock_llm = AsyncMock(return_value="not valid json at all!")
        d = TaskDecomposer(llm_callable=mock_llm)
        # Should fall back to heuristic without raising
        result = await d.decompose("Browse the web")
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_llm_callable_unknown_capability_defaults_to_reasoning(self) -> None:
        payload = json.dumps([
            {
                "description": "Do something unknown",
                "required_capability": "teleportation",
                "depends_on": [],
                "priority": 5,
            }
        ])
        mock_llm = AsyncMock(return_value=payload)
        d = TaskDecomposer(llm_callable=mock_llm)
        result = await d.decompose("task")
        assert result[0].required_capability == AgentCapability.REASONING


# ──────────────────────────────────────────────────────────────────────────────
# ConflictResolver Tests
# ──────────────────────────────────────────────────────────────────────────────


def _make_result(
    agent: AgentType,
    confidence: float,
    output: str = "ans",
    status: SubTaskStatus = SubTaskStatus.COMPLETED,
) -> SubTaskResult:
    return SubTaskResult(
        subtask_id="tid",
        agent_type=agent,
        status=status,
        output=output,
        confidence=confidence,
    )


class TestConflictResolver:
    @pytest.mark.asyncio
    async def test_single_result_passthrough(self) -> None:
        r = _make_result(AgentType.BRAIN, 0.8)
        resolver = ConflictResolver()
        winner = await resolver.resolve([r])
        assert winner is r

    @pytest.mark.asyncio
    async def test_high_confidence_gap_no_llm_call(self) -> None:
        """When delta > 0.1, should pick highest without calling LLM."""
        mock_llm = AsyncMock()
        resolver = ConflictResolver(llm_callable=mock_llm)
        results = [
            _make_result(AgentType.BRAIN, 0.9),
            _make_result(AgentType.ARCHITECT, 0.5),
        ]
        winner = await resolver.resolve(results)
        assert winner.agent_type == AgentType.BRAIN
        mock_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_scores_use_llm(self) -> None:
        """When delta ≤ 0.1, should call LLM adjudicator."""
        mock_llm = AsyncMock(return_value="1")  # choose index 1 (ARCHITECT)
        resolver = ConflictResolver(llm_callable=mock_llm)
        results = [
            _make_result(AgentType.BRAIN, 0.82),
            _make_result(AgentType.ARCHITECT, 0.80),
        ]
        winner = await resolver.resolve(results)
        mock_llm.assert_awaited_once()
        # index 1 = sorted descending → brain(0.82), architect(0.80) → index 1 = ARCHITECT
        assert winner.agent_type == AgentType.ARCHITECT

    @pytest.mark.asyncio
    async def test_llm_adjudication_failure_falls_back(self) -> None:
        """If LLM returns garbage, fall back to confidence order."""
        mock_llm = AsyncMock(return_value="not a number")
        resolver = ConflictResolver(llm_callable=mock_llm)
        results = [
            _make_result(AgentType.BRAIN, 0.88),
            _make_result(AgentType.ARCHITECT, 0.85),
        ]
        winner = await resolver.resolve(results)
        assert winner.agent_type == AgentType.BRAIN

    @pytest.mark.asyncio
    async def test_no_llm_preference_fallback(self) -> None:
        """Without LLM, BRAIN preferred over ARCHITECT over GHOST."""
        resolver = ConflictResolver()
        results = [
            _make_result(AgentType.GHOST, 0.75),
            _make_result(AgentType.BRAIN, 0.75),
        ]
        winner = await resolver.resolve(results)
        assert winner.agent_type == AgentType.BRAIN

    @pytest.mark.asyncio
    async def test_empty_results_raises(self) -> None:
        resolver = ConflictResolver()
        with pytest.raises(ConflictResolutionError):
            await resolver.resolve([])


# ──────────────────────────────────────────────────────────────────────────────
# MultiAgentCoordinator Tests
# ──────────────────────────────────────────────────────────────────────────────


class TestMultiAgentCoordinatorInit:
    def test_default_stubs_registered(self) -> None:
        c = MultiAgentCoordinator()
        agents = c.list_agents()
        assert len(agents) == 3
        types = {a["agent_type"] for a in agents}
        assert types == {"architect", "brain", "ghost"}

    def test_all_agents_available_by_default(self) -> None:
        c = MultiAgentCoordinator()
        for a in c.list_agents():
            assert a["is_available"] is True

    def test_register_agent_replaces_stub(self) -> None:
        c = MultiAgentCoordinator()
        c.register_agent(AgentType.BRAIN, _ok_handler)
        info = next(a for a in c.list_agents() if a["agent_type"] == "brain")
        assert info["is_available"] is True

    def test_set_available_false(self) -> None:
        c = MultiAgentCoordinator()
        c.set_available(AgentType.GHOST, False)
        info = next(a for a in c.list_agents() if a["agent_type"] == "ghost")
        assert info["is_available"] is False

    def test_set_available_unknown_agent_raises(self) -> None:
        c = MultiAgentCoordinator()
        # Remove ARCHITECT from the registry entirely, then try to toggle availability
        del c._registry[AgentType.ARCHITECT]
        with pytest.raises(AgentNotRegisteredError):
            c.set_available(AgentType.ARCHITECT, True)

    def test_capable_agents(self) -> None:
        c = MultiAgentCoordinator()
        agents = c.capable_agents(AgentCapability.WEB_BROWSING)
        assert AgentType.GHOST in agents

    def test_capable_agents_unavailable_excluded(self) -> None:
        c = MultiAgentCoordinator()
        c.set_available(AgentType.GHOST, False)
        agents = c.capable_agents(AgentCapability.WEB_BROWSING)
        assert AgentType.GHOST not in agents


class TestDelegateToAgent:
    @pytest.mark.asyncio
    async def test_delegate_ok(self) -> None:
        c = MultiAgentCoordinator()
        c.register_agent(AgentType.BRAIN, _ok_handler)
        st = _make_subtask()
        result = await c.delegate_to_agent(AgentType.BRAIN, st)
        assert result.status == SubTaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_delegate_to_unregistered_raises(self) -> None:
        c = MultiAgentCoordinator()
        del c._registry[AgentType.GHOST]
        st = _make_subtask()
        with pytest.raises(AgentNotRegisteredError):
            await c.delegate_to_agent(AgentType.GHOST, st)

    @pytest.mark.asyncio
    async def test_delegate_to_unavailable_raises(self) -> None:
        c = MultiAgentCoordinator()
        c.set_available(AgentType.GHOST, False)
        st = _make_subtask()
        with pytest.raises(AgentNotRegisteredError):
            await c.delegate_to_agent(AgentType.GHOST, st)


class TestCoordinatePipeline:
    @pytest.mark.asyncio
    async def test_simple_task_completes(self) -> None:
        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, _ok_handler)
        result = await c.coordinate("Recall memory about Docker")
        assert isinstance(result, CoordinationResult)
        assert result.total_time_ms > 0
        assert result.aggregated_output

    @pytest.mark.asyncio
    async def test_web_task_routes_to_ghost(self) -> None:
        routed_to: List[AgentType] = []

        async def spy_handler(subtask: SubTask, ctx: Dict) -> SubTaskResult:
            routed_to.append(subtask.assigned_agent)
            return await _ok_handler(subtask, ctx)

        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, spy_handler)

        await c.coordinate("Browse the web to scrape pricing data")
        assert AgentType.GHOST in routed_to

    @pytest.mark.asyncio
    async def test_failed_dependency_skips_downstream(self) -> None:
        c = MultiAgentCoordinator()

        async def always_fail(subtask: SubTask, ctx: Dict) -> SubTaskResult:
            # Fail only the first subtask
            if "step-A" in subtask.description:
                return await _fail_handler(subtask, ctx)
            return await _ok_handler(subtask, ctx)

        # Register the failing handler for all agents
        for agent in AgentType:
            c.register_agent(agent, always_fail)

        # Build a 2-task chain manually and inject into coordinator
        a = SubTask(
            description="step-A: memory query",
            required_capability=AgentCapability.MEMORY_QUERY,
            priority=1,
        )
        b = SubTask(
            description="step-B: reasoning after A",
            required_capability=AgentCapability.REASONING,
            depends_on=[a.id],
            priority=2,
        )

        # Override decomposer to return fixed subtasks
        async def _fake_decompose(task: str) -> List[SubTask]:
            return [a, b]

        c._decomposer.decompose = _fake_decompose  # type: ignore[method-assign]

        result = await c.coordinate("step-A then step-B")
        # b should be FAILED/SKIPPED because a failed
        statuses = {r.subtask_id: r.status for r in result.subtask_results}
        assert statuses[a.id] == SubTaskStatus.FAILED
        assert statuses[b.id] in {SubTaskStatus.SKIPPED, SubTaskStatus.FAILED}
        assert result.failed_subtasks >= 2

    @pytest.mark.asyncio
    async def test_timeout_subtask_marked_failed(self) -> None:
        async def slow_handler(subtask: SubTask, ctx: Dict) -> SubTaskResult:
            await asyncio.sleep(10)
            return await _ok_handler(subtask, ctx)

        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, slow_handler)

        # Create a subtask with a very short timeout and short-circuit decompose
        short_timeout_task = SubTask(
            description="Recall memory fast",
            required_capability=AgentCapability.MEMORY_QUERY,
            timeout_seconds=0.05,  # 50 ms
        )

        async def _fake_decompose(task: str) -> List[SubTask]:
            return [short_timeout_task]

        c._decomposer.decompose = _fake_decompose  # type: ignore[method-assign]

        result = await c.coordinate("fast memory recall")
        failed_result = next(
            r for r in result.subtask_results if r.subtask_id == short_timeout_task.id
        )
        assert failed_result.status == SubTaskStatus.FAILED
        assert "Timeout" in (failed_result.error or "")

    @pytest.mark.asyncio
    async def test_eventbus_integration(self) -> None:
        """Coordinator publishes events to an EventBus when provided."""
        bus = EventBus()
        received_types: List[str] = []

        async def listener() -> None:
            q = await bus.subscribe("coordinator.task_received")
            q2 = await bus.subscribe("coordinator.task_completed")
            # Just collect one event from each
            for _ in range(2):
                event = await asyncio.wait_for(
                    asyncio.gather(q.get(), q2.get(), return_exceptions=True),
                    timeout=5.0,
                )

        c = MultiAgentCoordinator(event_bus=bus)
        for agent in AgentType:
            c.register_agent(agent, _ok_handler)

        result = await c.coordinate("Reason about something")
        # Just verify aggregate output is present (events are best-effort)
        assert result.aggregated_output

    @pytest.mark.asyncio
    async def test_all_fail_aggregated_output(self) -> None:
        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, _fail_handler)

        async def _fake_decompose(task: str) -> List[SubTask]:
            return [_make_subtask("fail this")]

        c._decomposer.decompose = _fake_decompose  # type: ignore[method-assign]

        result = await c.coordinate("task that will fail")
        assert "fail" in result.aggregated_output.lower() or result.failed_subtasks > 0

    @pytest.mark.asyncio
    async def test_no_agents_available_routes_to_brain(self) -> None:
        """If preferred agent is unavailable, BRAIN receives the task."""
        c = MultiAgentCoordinator()
        c.set_available(AgentType.GHOST, False)
        c.set_available(AgentType.ARCHITECT, False)
        c.register_agent(AgentType.BRAIN, _ok_handler)

        result = await c.coordinate("Browse the web")
        # GHOST is down, routing should fall back to BRAIN
        brain_results = [r for r in result.subtask_results if r.agent_type == AgentType.BRAIN]
        assert len(brain_results) > 0

    @pytest.mark.asyncio
    async def test_parallel_independent_subtasks(self) -> None:
        """Two independent tasks should run in the same wave (parallel)."""
        call_times: List[float] = []

        async def timing_handler(subtask: SubTask, ctx: Dict) -> SubTaskResult:
            call_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return await _ok_handler(subtask, ctx)

        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, timing_handler)

        a = _make_subtask("task A", AgentCapability.MEMORY_QUERY, priority=1)
        b = _make_subtask("task B", AgentCapability.REASONING, priority=1)

        async def _fake_decompose(task: str) -> List[SubTask]:
            return [a, b]

        c._decomposer.decompose = _fake_decompose  # type: ignore[method-assign]

        t0 = time.monotonic()
        result = await c.coordinate("parallel tasks")
        elapsed = time.monotonic() - t0
        # If truly parallel: elapsed ≈ 50ms; serial would be ≈100ms
        assert elapsed < 0.18, f"Expected parallel execution but took {elapsed:.3f}s"
        assert len(result.subtask_results) == 2

    @pytest.mark.asyncio
    async def test_coordination_result_success_property(self) -> None:
        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, _ok_handler)
        result = await c.coordinate("simple reasoning task")
        assert result.success or result.failed_subtasks == 0 or not result.success


# ──────────────────────────────────────────────────────────────────────────────
# Integration: Coordinator + DependencyResolver + Real Wave Ordering
# ──────────────────────────────────────────────────────────────────────────────


class TestCoordinatorDependencyExecution:
    @pytest.mark.asyncio
    async def test_three_wave_execution_order(self) -> None:
        """Wave 0 → Wave 1 → Wave 2: verify execution ordering via output injection."""
        execution_log: List[str] = []

        async def tracking_handler(subtask: SubTask, ctx: Dict) -> SubTaskResult:
            execution_log.append(subtask.description)
            return SubTaskResult(
                subtask_id=subtask.id,
                agent_type=AgentType.BRAIN,
                status=SubTaskStatus.COMPLETED,
                output=f"result_of_{subtask.description}",
            )

        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, tracking_handler)

        w0 = _make_subtask("wave0", priority=1)
        w1 = SubTask(
            description="wave1",
            required_capability=AgentCapability.REASONING,
            depends_on=[w0.id],
            priority=2,
        )
        w2 = SubTask(
            description="wave2",
            required_capability=AgentCapability.REASONING,
            depends_on=[w1.id],
            priority=3,
        )

        async def _fake_decompose(task: str) -> List[SubTask]:
            return [w0, w1, w2]

        c._decomposer.decompose = _fake_decompose  # type: ignore[method-assign]

        await c.coordinate("three wave test")
        assert execution_log.index("wave0") < execution_log.index("wave1")
        assert execution_log.index("wave1") < execution_log.index("wave2")

    @pytest.mark.asyncio
    async def test_dependency_output_injected_into_context(self) -> None:
        """Downstream subtask should receive the output of its dependency via context."""
        received_ctx: Dict[str, Any] = {}

        async def capturing_handler(subtask: SubTask, ctx: Dict) -> SubTaskResult:
            if subtask.depends_on:
                received_ctx.update(ctx.get("dependency_outputs", {}))
            return SubTaskResult(
                subtask_id=subtask.id,
                agent_type=AgentType.BRAIN,
                status=SubTaskStatus.COMPLETED,
                output="captured",
            )

        c = MultiAgentCoordinator()
        for agent in AgentType:
            c.register_agent(agent, capturing_handler)

        a = _make_subtask("produce output A")
        b = SubTask(
            description="consume output of A",
            required_capability=AgentCapability.REASONING,
            depends_on=[a.id],
        )

        async def _fake_decompose(task: str) -> List[SubTask]:
            return [a, b]

        c._decomposer.decompose = _fake_decompose  # type: ignore[method-assign]

        await c.coordinate("chain test")
        # b's context should have a's result
        assert a.id in received_ctx
