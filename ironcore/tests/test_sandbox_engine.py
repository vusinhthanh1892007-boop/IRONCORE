from __future__ import annotations

import asyncio
import os

import pytest

from ironcore.core.engine import EventBus
from ironcore.tests.conftest import FakeContainer
from ironcore.sandbox import engine as sandbox_mod
from ironcore.sandbox.engine import NetworkPolicy, RuntimeType, SandboxPolicy


@pytest.mark.asyncio
async def test_spawn_applies_security_flags(sandbox_engine: sandbox_mod.SandboxEngine) -> None:
    policy = SandboxPolicy(network=NetworkPolicy.NONE, max_execution_seconds=1)

    await sandbox_engine.spawn_and_execute(
        skill_name="demo_skill",
        command="python -c print(123)",
        policy=policy,
    )
    run_kwargs = sandbox_engine._fake_client.containers.last_run_kwargs

    assert run_kwargs is not None
    assert run_kwargs["network_mode"] == "none"
    assert run_kwargs["read_only"] is True
    assert run_kwargs["cap_drop"] == ["ALL"]
    assert run_kwargs["security_opt"] == ["no-new-privileges"]


def test_spawn_applies_memory_limit(sandbox_engine: sandbox_mod.SandboxEngine) -> None:
    kwargs = sandbox_engine._build_run_kwargs(
        container_name="ironcore_sb_demo_123",
        skill_name="demo",
        command="python -c print(123)",
        policy=SandboxPolicy(max_memory_mb=512),
        runtime_used=RuntimeType.DOCKER,
    )

    assert kwargs["mem_limit"] == "512m"
    assert kwargs["memswap_limit"] == "512m"
    assert kwargs["cpu_quota"] == 50_000


@pytest.mark.asyncio
async def test_timeout_kills_container(sandbox_engine: sandbox_mod.SandboxEngine) -> None:
    container = FakeContainer(wait_delay=0.2)

    exit_code, timed_out = await sandbox_engine._wait_for_completion(container, timeout_seconds=0.01)

    assert exit_code == -1
    assert timed_out is True
    assert container.killed is True


@pytest.mark.asyncio
async def test_destroy_called_on_exception(
    sandbox_engine: sandbox_mod.SandboxEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destroyed = {"called": False}
    container = sandbox_engine._fake_client.containers.next_container

    async def explode(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("forced failure")

    async def track_destroy(current, name):
        del current, name
        destroyed["called"] = True

    monkeypatch.setattr(sandbox_engine, "_wait_for_completion", explode)
    monkeypatch.setattr(sandbox_engine, "_destroy_container", track_destroy)

    with pytest.raises(RuntimeError, match="forced failure"):
        await sandbox_engine.spawn_and_execute(
            skill_name="demo_skill",
            command="python -c print(123)",
            policy=SandboxPolicy(max_execution_seconds=1),
        )

    assert destroyed["called"] is True
    assert container is not None


@pytest.mark.asyncio
async def test_gvisor_runtime_injection(
    sandbox_engine: sandbox_mod.SandboxEngine,
    event_bus: EventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = event_bus.subscribe("sandbox.runtime_fallback")
    monkeypatch.setattr(sandbox_mod.GVisorAvailabilityChecker, "is_available", staticmethod(lambda: False))

    runtime = await sandbox_engine._resolve_runtime(RuntimeType.GVISOR)
    event = await asyncio.wait_for(queue.get(), timeout=0.2)

    assert runtime == RuntimeType.DOCKER
    assert event.payload["requested_runtime"] == "runsc"


@pytest.mark.skipif(
    os.environ.get("IRONCORE_RUN_INTEGRATION") != "1",
    reason="Set IRONCORE_RUN_INTEGRATION=1 to run Docker integration tests.",
)
@pytest.mark.asyncio
async def test_sandbox_engine_integration_guard() -> None:
    pytest.importorskip("docker")
    try:
        engine = sandbox_mod.SandboxEngine()
    except (ImportError, ConnectionError):
        pytest.skip("Docker daemon unavailable for integration test.")

    try:
        result = await engine.spawn_and_execute(
            skill_name="integration_demo",
            command="python -c print(123)",
            policy=SandboxPolicy(max_execution_seconds=5),
        )
        assert result.exit_code == 0
    finally:
        engine.close()
