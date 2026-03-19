"""
IronCore: Async Core Engine
===========================
Production-grade, event-driven AI agent core with validated data models.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from enum import Enum, auto
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable["Observation | Any"]]


class RiskLevel(Enum):
    """Tiered risk classification for every agent action."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ActionStatus(Enum):
    """Lifecycle states of an action."""

    PENDING = auto()
    APPROVED = auto()
    REJECTED = auto()
    EXECUTED = auto()
    FAILED = auto()


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class Event(BaseModel):
    """Immutable event published on the async event bus."""

    model_config = ConfigDict(frozen=True)

    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)


class Action(BaseModel):
    """
    Represents a single agent decision: which tool to call and with what args.

    Attributes:
        tool_name: Registered tool identifier.
        args: Keyword arguments forwarded to the tool handler.
        action_id: Unique UUID for tracing.
        risk_level: Override risk; merged with registered tool risk.
        requires_sandbox: Force sandbox isolation regardless of tool default.
        requires_human_approval: Force human approval regardless of risk level.
    """

    tool_name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    risk_level: RiskLevel = RiskLevel.LOW
    requires_sandbox: bool = False
    requires_human_approval: bool = False

    @field_validator("tool_name")
    @classmethod
    def tool_name_not_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool_name cannot be empty")
        return normalized


class Observation(BaseModel):
    """Immutable result returned after an action is dispatched."""

    model_config = ConfigDict(frozen=True)

    content: Any
    status: str = "success"
    action_id: Optional[str] = None
    error: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class ToolDefinition(BaseModel):
    """Metadata contract for registering a tool with IronCoreEngine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    handler: ToolHandler
    risk_level: RiskLevel = RiskLevel.LOW
    requires_sandbox: bool = False
    description: str = ""

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tool name cannot be empty")
        return normalized


class CircuitBreakerStatus(BaseModel):
    """Serializable circuit breaker state snapshot."""

    state: CircuitState
    failure_count: int
    failure_threshold: int
    base_reset_timeout: float
    current_reset_timeout: float
    max_reset_timeout: float
    backoff_multiplier: float
    last_failure_time: Optional[float] = None
    seconds_until_half_open: float = 0.0


@runtime_checkable
class LLMBridgeProtocol(Protocol):
    """Contract for pluggable LLM providers."""

    async def get_next_action(
        self,
        history: List[Dict[str, Any]],
        available_tools: List[ToolDefinition],
        system_prompt: str,
    ) -> Optional[Action]:
        """Return the next action to execute, or None to stop the loop."""


class StubLLMBridge:
    """Fallback bridge used when no real LLM provider is injected."""

    async def get_next_action(
        self,
        history: List[Dict[str, Any]],
        available_tools: List[ToolDefinition],
        system_prompt: str,
    ) -> Optional[Action]:
        del history, available_tools, system_prompt
        logger.debug("[IronCore] StubLLMBridge returning a finish action.")
        return Action(
            tool_name="finish",
            args={"answer": "Stub: LLM provider not yet connected."},
        )


class ActionSerializer:
    """Helpers for converting actions into LLM-friendly history records."""

    @staticmethod
    def to_dict(action: Action) -> Dict[str, Any]:
        return {
            "role": "assistant",
            "tool": action.tool_name,
            "args": action.args,
            "action_id": action.action_id,
            "risk_level": action.risk_level.name,
            "requires_sandbox": action.requires_sandbox,
            "requires_human_approval": action.requires_human_approval,
        }

    @staticmethod
    def to_json(action: Action) -> str:
        return json.dumps(ActionSerializer.to_dict(action), sort_keys=True)


class CircuitBreaker:
    """
    Fault-tolerance guard for the agent loop.

    Transitions:
      CLOSED    -> OPEN      after failure threshold is reached
      OPEN      -> HALF_OPEN after reset timeout elapses
      HALF_OPEN -> CLOSED    after a success
      HALF_OPEN -> OPEN      after a failure
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        backoff_multiplier: float = 2.0,
        max_reset_timeout: float = 3600.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._base_reset_timeout = reset_timeout
        self._current_reset_timeout = reset_timeout
        self._backoff_multiplier = backoff_multiplier
        self._max_reset_timeout = max_reset_timeout
        self._failures = 0
        self._last_failure_time: Optional[float] = None
        self._state = CircuitState.CLOSED
        self._trip_count = 0

    def record_success(self) -> Optional[CircuitBreakerStatus]:
        """Reset failure tracking and close the circuit if needed."""
        previous_state = self._state
        self._failures = 0
        self._last_failure_time = None
        self._state = CircuitState.CLOSED
        self._current_reset_timeout = self._base_reset_timeout
        self._trip_count = 0
        if previous_state != self._state:
            logger.info("[CircuitBreaker] Transitioned to CLOSED.")
            return self.get_status()
        return None

    def record_failure(self) -> Optional[CircuitBreakerStatus]:
        """Increment failure count and trip the breaker if required."""
        previous_state = self._state
        self._failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._trip()
        elif self._state == CircuitState.CLOSED and self._failures >= self._failure_threshold:
            self._trip()

        if previous_state != self._state:
            logger.critical(
                "[CircuitBreaker] Transitioned to %s after %s consecutive failures.",
                self._state.value,
                self._failures,
            )
            return self.get_status()
        return None

    def poll_state(self) -> Optional[CircuitBreakerStatus]:
        """Advance OPEN -> HALF_OPEN once the timeout has elapsed."""
        if self._state != CircuitState.OPEN or self._last_failure_time is None:
            return None

        elapsed = time.time() - self._last_failure_time
        if elapsed >= self._current_reset_timeout:
            self._state = CircuitState.HALF_OPEN
            logger.info("[CircuitBreaker] Transitioned to HALF_OPEN.")
            return self.get_status()
        return None

    def get_status(self) -> CircuitBreakerStatus:
        """Return the current circuit breaker state as a Pydantic model."""
        seconds_until_half_open = 0.0
        if self._state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.time() - self._last_failure_time
            seconds_until_half_open = max(0.0, self._current_reset_timeout - elapsed)

        return CircuitBreakerStatus(
            state=self._state,
            failure_count=self._failures,
            failure_threshold=self._failure_threshold,
            base_reset_timeout=self._base_reset_timeout,
            current_reset_timeout=self._current_reset_timeout,
            max_reset_timeout=self._max_reset_timeout,
            backoff_multiplier=self._backoff_multiplier,
            last_failure_time=self._last_failure_time,
            seconds_until_half_open=seconds_until_half_open,
        )

    @property
    def is_open(self) -> bool:
        """True if the circuit is currently OPEN."""
        return self._state == CircuitState.OPEN

    def _trip(self) -> None:
        """Transition to OPEN and increase reset timeout with exponential backoff."""
        if self._trip_count == 0:
            self._current_reset_timeout = self._base_reset_timeout
        else:
            self._current_reset_timeout = min(
                self._current_reset_timeout * self._backoff_multiplier,
                self._max_reset_timeout,
            )
        self._trip_count += 1
        self._state = CircuitState.OPEN


class HumanInTheLoop:
    """
    Approval gateway that intercepts actions above a configurable risk threshold.

    LOW and MEDIUM are auto-approved by policy.
    HIGH and CRITICAL require explicit approval unless disabled upstream.
    """

    def __init__(self, auto_approve_below: RiskLevel = RiskLevel.HIGH) -> None:
        self._auto_approve_below = auto_approve_below

    async def request_approval(self, action: Action) -> bool:
        """
        Evaluate whether an action is allowed to proceed.

        Args:
            action: The action about to be dispatched.

        Returns:
            True if approved, otherwise False.
        """
        if (
            not action.requires_human_approval
            and action.risk_level.value < self._auto_approve_below.value
        ):
            logger.info(
                "[HITL] Auto-approved tool=%s risk=%s",
                action.tool_name,
                action.risk_level.name,
            )
            return True

        logger.warning(
            "\n╔══════════════════════════════════════════════════╗\n"
            "║         !! HUMAN APPROVAL REQUIRED !!           ║\n"
            "╠══════════════════════════════════════════════════╣\n"
            f"║ Tool   : {action.tool_name:<40}║\n"
            f"║ Risk   : {action.risk_level.name:<40}║\n"
            f"║ Args   : {str(action.args)[:40]:<40}║\n"
            f"║ ID     : {action.action_id[:36]:<40}║\n"
            "╚══════════════════════════════════════════════════╝"
        )

        loop = asyncio.get_running_loop()
        approved = False

        while True:
            try:
                raw = await loop.run_in_executor(
                    None,
                    lambda: input(
                        f"[HITL] Approve '{action.tool_name}' "
                        f"(risk={action.risk_level.name})? [y/N]: "
                    ),
                )
            except Exception as exc:
                logger.error(
                    "[HITL] Approval channel failed (%s). Defaulting to REJECT.",
                    exc,
                )
                return False

            answer = raw.strip().lower()
            if answer in {"y", "yes"}:
                approved = True
                break
            if answer in {"", "n", "no"}:
                approved = False
                break

            logger.warning("[HITL] Invalid input '%s'. Please enter y or n.", raw.strip())

        logger.info(
            "[HITL] Action %s -> %s by human.",
            action.action_id,
            "APPROVED" if approved else "REJECTED",
        )
        return approved


class EventBus:
    """
    Async pub/sub event bus.

    Subscribers receive events on individual asyncio queues so slow consumers
    cannot block fast ones.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue[Event]]] = {}
        self._global_queue: asyncio.Queue[Event] = asyncio.Queue()

    def subscribe(self, event_type: str) -> "asyncio.Queue[Event]":
        """Register interest in a specific event type."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(event_type, []).append(queue)
        logger.debug("[EventBus] Subscribed to event_type=%s", event_type)
        return queue

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers and the global queue."""
        await self._global_queue.put(event)
        for queue in self._subscribers.get(event.event_type, []):
            await queue.put(event)
        logger.debug("[EventBus] Published event_type=%s id=%s", event.event_type, event.event_id)

    async def consume_all(self) -> AsyncIterator[Event]:
        """Yield every event from the global queue."""
        while True:
            event = await self._global_queue.get()
            try:
                yield event
            finally:
                self._global_queue.task_done()


class IronCoreEngine:
    """
    IronCore's central async agent engine.

    Responsibilities:
      1. Tool registry
      2. Human approval gate
      3. Circuit breaker protection
      4. Event publication
      5. ReAct history lifecycle
    """

    def __init__(
        self,
        hitl: Optional[HumanInTheLoop] = None,
        llm_bridge: Optional[LLMBridgeProtocol] = None,
        max_iterations: int = 50,
        max_history_items: int = 100,
        system_prompt: str = "You are IronCore, a secure autonomous agent.",
    ) -> None:
        if max_iterations <= 0:
            raise ValueError("max_iterations must be greater than zero")
        if max_history_items <= 1:
            raise ValueError("max_history_items must be greater than one")

        self.event_bus = EventBus()
        self._hitl = hitl or HumanInTheLoop()
        self._llm_bridge: LLMBridgeProtocol = llm_bridge or StubLLMBridge()
        self._circuit_breaker = CircuitBreaker()
        self._max_iterations = max_iterations
        self._max_history_items = max_history_items
        self._system_prompt = system_prompt
        self._tools: Dict[str, ToolDefinition] = {}
        self._history: List[Dict[str, Any]] = []
        self._iteration = 0
        self._running = False

        if llm_bridge is None:
            logger.warning(
                "[IronCore] No llm_bridge injected. Falling back to StubLLMBridge."
            )

        self._register_builtin_tools()
        logger.info("[IronCore] Engine initialized. Call run_loop() to start.")

    def _register_builtin_tools(self) -> None:
        """Register the minimal built-in tool set."""
        self.register_tool(
            ToolDefinition(
                name="think",
                handler=self._tool_think,
                risk_level=RiskLevel.LOW,
                description="Internal reasoning step with no side effects.",
            )
        )
        self.register_tool(
            ToolDefinition(
                name="finish",
                handler=self._tool_finish,
                risk_level=RiskLevel.LOW,
                description="Terminate the run loop and return the final answer.",
            )
        )

    def register_tool(self, tool: ToolDefinition) -> None:
        """Register an external tool with the engine."""
        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                "Use a different name or deregister the existing one first."
            )
        self._tools[tool.name] = tool
        logger.info(
            "[IronCore] Registered tool=%s risk=%s sandbox=%s",
            tool.name,
            tool.risk_level.name,
            tool.requires_sandbox,
        )

    def deregister_tool(self, tool_name: str) -> None:
        """Remove a tool from the registry."""
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' is not registered.")
        del self._tools[tool_name]
        logger.info("[IronCore] Deregistered tool=%s", tool_name)

    async def _tool_think(self, thought: str = "", **_: Any) -> Observation:
        """Chain-of-thought reasoning step. Always safe; no side effects."""
        logger.info("[Think] %s", thought)
        return Observation(content=thought, status="success")

    async def _tool_finish(self, answer: str = "", **_: Any) -> Observation:
        """Terminate the agent loop and return the final answer."""
        self._running = False
        logger.info("[Finish] Task complete: %s", answer)
        return Observation(content=answer, status="finished")

    async def dispatch(self, action: Action) -> Observation:
        """
        Route an action through approval and execute it.

        Args:
            action: The action to execute.

        Returns:
            Observation containing the tool output or error details.
        """
        tool_def = self._tools.get(action.tool_name)
        if tool_def is None:
            transition = self._circuit_breaker.record_failure()
            if transition is not None:
                await self._publish_circuit_breaker_state(transition)
            return Observation(
                content=None,
                status="error",
                action_id=action.action_id,
                error=f"Unknown tool: '{action.tool_name}'. Available: {list(self._tools.keys())}",
            )

        effective_risk = max(action.risk_level, tool_def.risk_level, key=lambda level: level.value)
        effective_action = action.model_copy(
            update={
                "risk_level": effective_risk,
                "requires_sandbox": action.requires_sandbox or tool_def.requires_sandbox,
            }
        )

        approved = await self._hitl.request_approval(effective_action)
        if not approved:
            observation = Observation(
                content=None,
                status="rejected",
                action_id=effective_action.action_id,
                error="Action rejected by Human-in-the-Loop policy.",
            )
            await self.event_bus.publish(
                Event(
                    event_type="action.rejected",
                    payload={
                        "tool": effective_action.tool_name,
                        "action_id": effective_action.action_id,
                    },
                )
            )
            return observation

        try:
            result = await tool_def.handler(**effective_action.args)
            observation = self._normalize_observation(
                result=result,
                action_id=effective_action.action_id,
            )
            transition = self._circuit_breaker.record_success()
            if transition is not None:
                await self._publish_circuit_breaker_state(transition)
            await self.event_bus.publish(
                Event(
                    event_type="action.completed",
                    payload={
                        "tool": effective_action.tool_name,
                        "action_id": effective_action.action_id,
                        "status": observation.status,
                        "iteration": self._iteration,
                        "requires_sandbox": effective_action.requires_sandbox,
                    },
                )
            )
            logger.info(
                "[IronCore] Executed tool=%s status=%s",
                effective_action.tool_name,
                observation.status,
            )
            return observation
        except Exception as exc:
            transition = self._circuit_breaker.record_failure()
            if transition is not None:
                await self._publish_circuit_breaker_state(transition)
            logger.exception("[IronCore] Tool '%s' raised: %s", effective_action.tool_name, exc)
            observation = Observation(
                content=None,
                status="error",
                action_id=effective_action.action_id,
                error=str(exc),
            )
            await self.event_bus.publish(
                Event(
                    event_type="action.failed",
                    payload={
                        "tool": effective_action.tool_name,
                        "action_id": effective_action.action_id,
                        "error": str(exc),
                    },
                )
            )
            return observation

    async def run_loop(self, initial_prompt: str) -> List[Dict[str, Any]]:
        """
        Main async ReAct loop.

        Args:
            initial_prompt: The user task to solve.

        Returns:
            Full conversation history as a list of dicts.
        """
        self._running = True
        self._iteration = 0
        self._history = [{"role": "user", "content": initial_prompt}]

        await self.event_bus.publish(
            Event(
                event_type="agent.started",
                payload={
                    "prompt": initial_prompt,
                    "max_iterations": self._max_iterations,
                    "max_history_items": self._max_history_items,
                },
            )
        )
        logger.info("[IronCore] run_loop started max_iterations=%s", self._max_iterations)

        while self._running and self._iteration < self._max_iterations:
            transition = self._circuit_breaker.poll_state()
            if transition is not None:
                await self._publish_circuit_breaker_state(transition)

            if self._circuit_breaker.is_open:
                logger.critical("[IronCore] Circuit breaker is OPEN. Halting loop.")
                await self.event_bus.publish(
                    Event(event_type="agent.circuit_breaker_tripped", payload={})
                )
                break

            self._iteration += 1
            logger.info(
                "[IronCore] Iteration %s/%s",
                self._iteration,
                self._max_iterations,
            )

            try:
                action = await self._get_next_action()
            except Exception as exc:
                logger.error("[IronCore] LLM bridge failed: %s", exc)
                transition = self._circuit_breaker.record_failure()
                if transition is not None:
                    await self._publish_circuit_breaker_state(transition)
                continue

            if action is None:
                logger.warning("[IronCore] LLM bridge returned no action. Stopping.")
                break

            observation = await self.dispatch(action)
            self._record_history(action=action, observation=observation)

            await self.event_bus.publish(
                Event(
                    event_type="agent.observation",
                    payload={
                        "iteration": self._iteration,
                        "status": observation.status,
                        "tool": action.tool_name,
                    },
                )
            )

            if observation.status == "finished":
                break

        stop_reason = "finished" if not self._running else "loop_ended"
        if self._iteration >= self._max_iterations and self._running:
            stop_reason = "max_iterations"

        await self.event_bus.publish(
            Event(
                event_type="agent.stopped",
                payload={
                    "total_iterations": self._iteration,
                    "reason": stop_reason,
                },
            )
        )
        logger.info("[IronCore] Loop ended after %s iteration(s)", self._iteration)
        return self.history

    async def _get_next_action(self) -> Optional[Action]:
        """
        Ask the configured LLM bridge for the next action.

        Returns:
            The next validated Action, or None to stop the loop.
        """
        return await self._llm_bridge.get_next_action(
            history=self.export_history_for_llm(max_tokens=8_000),
            available_tools=list(self._tools.values()),
            system_prompt=self._system_prompt,
        )

    def export_history_for_llm(self, max_tokens: int) -> List[Dict[str, Any]]:
        """
        Export a trimmed history window for LLM consumption.

        Token counting is approximate and intentionally conservative.
        """
        if max_tokens <= 0:
            return []

        if not self._history:
            return []

        exported: List[Dict[str, Any]] = []
        running_tokens = 0
        for entry in reversed(self._history):
            estimated_tokens = self._estimate_tokens(entry)
            if exported and running_tokens + estimated_tokens > max_tokens:
                break
            exported.append(entry)
            running_tokens += estimated_tokens

        exported.reverse()
        return exported

    def _record_history(self, action: Action, observation: Observation) -> None:
        """Append a single action-observation pair to history and trim if needed."""
        self._history.append(ActionSerializer.to_dict(action))
        self._history.append(
            {
                "role": "observation",
                "content": observation.content,
                "status": observation.status,
                "error": observation.error,
                "action_id": observation.action_id,
                "timestamp": observation.timestamp,
            }
        )
        self._trim_history()

    def _trim_history(self) -> None:
        """Keep the first prompt plus the newest history items within the configured cap."""
        if len(self._history) <= self._max_history_items:
            return

        head = self._history[:1]
        tail_budget = max(0, self._max_history_items - len(head))
        trimmed = head + self._history[-tail_budget:]
        removed = len(self._history) - len(trimmed)
        self._history = trimmed
        logger.info("[IronCore] Trimmed %s history item(s)", removed)

    async def _publish_circuit_breaker_state(self, status: CircuitBreakerStatus) -> None:
        """Broadcast circuit breaker state transitions."""
        await self.event_bus.publish(
            Event(
                event_type="circuit_breaker.state_changed",
                payload=status.model_dump(),
            )
        )

    @staticmethod
    def _normalize_observation(result: Observation | Any, action_id: str) -> Observation:
        """Wrap non-Observation tool outputs into a standard Observation model."""
        if isinstance(result, Observation):
            return result.model_copy(update={"action_id": action_id})
        return Observation(content=result, status="success", action_id=action_id)

    @staticmethod
    def _estimate_tokens(entry: Dict[str, Any]) -> int:
        """Approximate token usage using a conservative chars-to-token heuristic."""
        serialized = json.dumps(entry, default=str, sort_keys=True)
        return max(1, len(serialized) // 4)

    @property
    def history(self) -> List[Dict[str, Any]]:
        """Read-only snapshot of the current history."""
        return [dict(entry) for entry in self._history]

    @property
    def iteration(self) -> int:
        """Current loop iteration count."""
        return self._iteration

    @property
    def registered_tools(self) -> List[str]:
        """List of all registered tool names."""
        return list(self._tools.keys())

    @property
    def llm_bridge(self) -> LLMBridgeProtocol:
        """Current LLM bridge instance."""
        return self._llm_bridge

    @property
    def circuit_breaker_status(self) -> CircuitBreakerStatus:
        """Current circuit breaker snapshot."""
        return self._circuit_breaker.get_status()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    async def _demo() -> None:
        engine = IronCoreEngine(max_iterations=5)
        history = await engine.run_loop(
            "Summarize the latest developments in AI safety research."
        )
        print("\n-- Final History --")
        for entry in history:
            print(entry)

    asyncio.run(_demo())
