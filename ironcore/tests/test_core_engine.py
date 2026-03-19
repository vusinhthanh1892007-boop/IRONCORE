from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from ironcore.core.engine import (
    Action,
    CircuitBreaker,
    CircuitState,
    Event,
    EventBus,
    HumanInTheLoop,
    IronCoreEngine,
    RiskLevel,
    ToolDefinition,
)


class SequenceLLMBridge:
    def __init__(self, actions: List[Optional[Action]]) -> None:
        self._actions = list(actions)

    async def get_next_action(
        self,
        history: List[Dict[str, Any]],
        available_tools: List[ToolDefinition],
        system_prompt: str,
    ) -> Optional[Action]:
        del history, available_tools, system_prompt
        if self._actions:
            return self._actions.pop(0)
        return None


@pytest.mark.asyncio
async def test_dispatch_known_tool(engine: IronCoreEngine) -> None:
    events = engine.event_bus.subscribe("action.completed")

    async def echo(message: str) -> Dict[str, str]:
        return {"echo": message}

    engine.register_tool(ToolDefinition(name="echo", handler=echo))
    observation = await engine.dispatch(Action(tool_name="echo", args={"message": "hello"}))
    event = await asyncio.wait_for(events.get(), timeout=0.2)

    assert observation.status == "success"
    assert observation.content == {"echo": "hello"}
    assert event.payload["tool"] == "echo"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(engine: IronCoreEngine) -> None:
    observation = await engine.dispatch(Action(tool_name="missing_tool"))

    assert observation.status == "error"
    assert "Unknown tool" in str(observation.error)
    assert engine.circuit_breaker_status.failure_count == 1


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_threshold(engine: IronCoreEngine) -> None:
    for _ in range(5):
        await engine.dispatch(Action(tool_name="missing_tool"))

    assert engine.circuit_breaker_status.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0.01)

    breaker.record_failure()
    assert breaker.get_status().state == CircuitState.OPEN

    await asyncio.sleep(0.02)
    transition = breaker.poll_state()
    assert transition is not None
    assert transition.state == CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.get_status().state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_hitl_auto_approve_low_risk() -> None:
    hitl = HumanInTheLoop()
    approved = await hitl.request_approval(Action(tool_name="think", risk_level=RiskLevel.LOW))
    assert approved is True


@pytest.mark.asyncio
async def test_hitl_blocks_critical_without_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    hitl = HumanInTheLoop()
    monkeypatch.setattr("builtins.input", lambda _: "n")

    approved = await hitl.request_approval(
        Action(
            tool_name="delete_everything",
            risk_level=RiskLevel.CRITICAL,
        )
    )
    assert approved is False


@pytest.mark.asyncio
async def test_run_loop_terminates_on_finish() -> None:
    engine = IronCoreEngine(max_iterations=3)
    stop_events = engine.event_bus.subscribe("agent.stopped")

    history = await engine.run_loop("Return a final answer.")
    stopped = await asyncio.wait_for(stop_events.get(), timeout=0.2)

    assert engine.iteration == 1
    assert stopped.payload["reason"] == "finished"
    assert history[-1]["status"] == "finished"


@pytest.mark.asyncio
async def test_run_loop_terminates_on_max_iterations() -> None:
    bridge = SequenceLLMBridge(
        [
            Action(tool_name="think", args={"thought": "step 1"}),
            Action(tool_name="think", args={"thought": "step 2"}),
            Action(tool_name="think", args={"thought": "step 3"}),
        ]
    )
    engine = IronCoreEngine(llm_bridge=bridge, max_iterations=2)
    stop_events = engine.event_bus.subscribe("agent.stopped")

    history = await engine.run_loop("Keep thinking.")
    stopped = await asyncio.wait_for(stop_events.get(), timeout=0.2)

    assert engine.iteration == 2
    assert stopped.payload["reason"] == "max_iterations"
    assert history[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_event_bus_fan_out() -> None:
    bus = EventBus()
    first = bus.subscribe("demo")
    second = bus.subscribe("demo")
    third = bus.subscribe("demo")

    await bus.publish(Event(event_type="demo", payload={"value": 1}))

    received = await asyncio.gather(first.get(), second.get(), third.get())
    assert [event.payload["value"] for event in received] == [1, 1, 1]
