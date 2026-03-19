from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pytest

from ironcore.core.engine import EventBus, IronCoreEngine, StubLLMBridge
from ironcore.security.policy_engine import (
    CumulativeRiskBudgetRule,
    DangerousArgPatternRule,
    DenylistRule,
    PolicyEngine,
    RateLimitRule,
    SandboxEscalationRule,
)
from ironcore.security.secrets_vault import SecretsVault
from ironcore.sandbox import engine as sandbox_mod


class FakeContainer:
    def __init__(
        self,
        *,
        wait_result: int = 0,
        wait_delay: float = 0.0,
        stdout: bytes = b"ok\n",
        stderr: bytes = b"",
    ) -> None:
        self.id = "container-id-123"
        self.short_id = "cont123"
        self.status = "running"
        self._wait_result = wait_result
        self._wait_delay = wait_delay
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False
        self.removed = False

    def wait(self) -> Dict[str, int]:
        if self._wait_delay:
            time.sleep(self._wait_delay)
        self.status = "exited"
        return {"StatusCode": self._wait_result}

    def kill(self) -> None:
        self.killed = True
        self.status = "killed"

    def remove(self, force: bool = True) -> None:
        del force
        self.removed = True

    def logs(self, stdout: bool = True, stderr: bool = False) -> bytes:
        if stdout and not stderr:
            return self._stdout
        if stderr and not stdout:
            return self._stderr
        return self._stdout + self._stderr

    def stats(self, stream: bool = False) -> Dict[str, Any]:
        del stream
        return {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 20},
                "system_cpu_usage": 40,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 10},
                "system_cpu_usage": 20,
            },
            "memory_stats": {"usage": 16 * 1024 * 1024, "limit": 64 * 1024 * 1024},
            "pids_stats": {"current": 2},
            "networks": {"eth0": {"rx_bytes": 128, "tx_bytes": 64}},
        }


class FakeContainersAPI:
    def __init__(self) -> None:
        self.last_run_kwargs: Optional[Dict[str, Any]] = None
        self.next_container = FakeContainer()
        self._listed: List[FakeContainer] = []

    def run(self, **kwargs: Any) -> FakeContainer:
        self.last_run_kwargs = kwargs
        container = self.next_container
        self._listed.append(container)
        self.next_container = FakeContainer()
        return container

    def list(self, all: bool = True, filters: Optional[Dict[str, str]] = None) -> List[FakeContainer]:
        del all, filters
        return list(self._listed)


class FakeImage:
    def __init__(self, digest: str = "sha256:local") -> None:
        self.attrs = {
            "RepoDigests": [f"python:3.11-alpine@{digest}"],
            "Id": digest,
        }


class FakeRegistryData:
    def __init__(self, digest: str = "sha256:local") -> None:
        self.attrs = {"Descriptor": {"digest": digest}}


class FakeImagesAPI:
    def __init__(self) -> None:
        self.image = FakeImage()
        self.registry = FakeRegistryData()
        self.pulled = False

    def get(self, image_name: str) -> FakeImage:
        del image_name
        return self.image

    def pull(self, image_name: str) -> FakeImage:
        del image_name
        self.pulled = True
        return self.image

    def get_registry_data(self, image_name: str) -> FakeRegistryData:
        del image_name
        return self.registry


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = FakeContainersAPI()
        self.images = FakeImagesAPI()
        self.closed = False

    def ping(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def engine() -> IronCoreEngine:
    return IronCoreEngine(
        llm_bridge=StubLLMBridge(),
        max_iterations=5,
        max_history_items=20,
    )


@pytest.fixture
def policy_engine() -> PolicyEngine:
    engine = PolicyEngine()
    engine.add_rule(DangerousArgPatternRule())
    engine.add_rule(DenylistRule({"raw_shell", "eval_python"}))
    engine.add_rule(RateLimitRule({"web_search": (200, 60.0), "send_email": (50, 60.0)}))
    engine.add_rule(SandboxEscalationRule({"run_python_script", "run_bash_script"}))
    engine.add_rule(CumulativeRiskBudgetRule(max_budget=1_500))
    return engine


@pytest.fixture
def vault() -> SecretsVault:
    pytest.importorskip("cryptography")
    vault = SecretsVault.from_passphrase(
        "ironcore-phase-7-tests",
        salt=b"phase7-fixture-1",
    )
    vault.store("IRONCORE_AUDIT_HMAC_KEY", "audit-signing-secret")
    vault.store("IRONCORE_API_KEY", "user-test-key")
    vault.store("IRONCORE_ADMIN_API_KEY", "admin-test-key")
    return vault


@pytest.fixture
def sandbox_engine(event_bus: EventBus) -> sandbox_mod.SandboxEngine:
    client = FakeDockerClient()
    engine = sandbox_mod.SandboxEngine.__new__(sandbox_mod.SandboxEngine)
    engine._client = client
    engine._event_bus = event_bus
    engine._active_containers = {}
    engine._image_cache = {}
    engine._fake_client = client
    return engine
