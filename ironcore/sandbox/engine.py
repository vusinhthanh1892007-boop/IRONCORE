"""
IronCore: Ephemeral Sandbox Engine
==================================
Production-grade container isolation for high-risk skill execution.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironcore.core.engine import Event, EventBus
from ironcore.security.policy_engine import DangerousArgPatternRule, PolicyVerdict

logger = logging.getLogger(__name__)

try:
    import docker
    from docker.errors import APIError, DockerException, ImageNotFound, NotFound
    from docker.models.containers import Container

    _DOCKER_AVAILABLE = True
except ImportError:
    docker = None
    _DOCKER_AVAILABLE = False

    class DockerException(Exception):
        """Fallback exception when docker SDK is unavailable."""

    class APIError(DockerException):
        """Fallback API error when docker SDK is unavailable."""

    class ImageNotFound(DockerException):
        """Fallback image lookup error when docker SDK is unavailable."""

    class NotFound(DockerException):
        """Fallback container lookup error when docker SDK is unavailable."""

    Container = Any


class NetworkPolicy(str, Enum):
    """Container network isolation levels."""

    NONE = "none"
    INTERNAL = "bridge"
    HOST = "host"


class RuntimeType(str, Enum):
    """Container runtime options supported by SandboxEngine."""

    DOCKER = "runc"
    GVISOR = "runsc"


class SandboxValidationError(RuntimeError):
    """Raised when a command/image/policy fails pre-execution validation."""

    def __init__(self, violations: List[str]) -> None:
        self.violations = violations
        super().__init__("Sandbox validation failed: " + "; ".join(violations))


class GVisorAvailabilityChecker:
    """Detect whether the `runsc` runtime is available on the host."""

    @staticmethod
    def is_available() -> bool:
        return shutil.which(RuntimeType.GVISOR.value) is not None


class SandboxPolicy(BaseModel):
    """Security and resource contract for a single sandboxed execution."""

    model_config = ConfigDict(use_enum_values=False)

    image: str = "python:3.11-alpine"
    network: NetworkPolicy = NetworkPolicy.NONE
    runtime: RuntimeType = RuntimeType.DOCKER
    readonly_root: bool = True
    writable_dirs: List[str] = Field(default_factory=lambda: ["/tmp"])
    max_cpu_quota: int = 50_000
    max_memory_mb: int = 256
    max_execution_seconds: int = 30
    drop_capabilities: List[str] = Field(default_factory=lambda: ["ALL"])
    extra_env: Dict[str, str] = Field(default_factory=dict)
    pull_if_missing: bool = True

    @field_validator("image")
    @classmethod
    def image_not_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("image cannot be empty")
        return normalized


class ContainerHealthMetrics(BaseModel):
    """Point-in-time resource metrics for a running container."""

    cpu_percent: float
    memory_mb: float
    memory_percent: float
    pids: int
    network_rx_bytes: int
    network_tx_bytes: int
    status: str
    timestamp: float = Field(default_factory=time.time)


class ValidationResult(BaseModel):
    """Result of pre-execution sandbox validation."""

    valid: bool
    violations: List[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """Full result of one sandboxed skill run."""

    model_config = ConfigDict(use_enum_values=False)

    container_id: str
    container_short: str
    skill_name: str
    stdout: str
    stderr: str
    exit_code: int
    execution_time_s: float
    timed_out: bool = False
    image_used: str = ""
    health_metrics: List[ContainerHealthMetrics] = Field(default_factory=list)
    peak_memory_mb: float = 0.0
    image_digest: Optional[str] = None
    runtime_used: RuntimeType = RuntimeType.DOCKER
    security_violations: List[str] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def summary(self) -> str:
        status = "OK" if self.succeeded else ("TIMEOUT" if self.timed_out else "FAIL")
        return (
            f"[{status}] skill={self.skill_name} "
            f"container={self.container_short} exit={self.exit_code} "
            f"runtime={self.runtime_used.value} peak_mem={self.peak_memory_mb:.1f}MB "
            f"time={self.execution_time_s:.2f}s"
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ExecutionResult":
        return cls.model_validate(payload)


class SandboxEngine:
    """
    IronCore Docker-backed isolation layer.

    Each spawn_and_execute() call:
      1. validates the execution context
      2. resolves runtime (`runc` or `runsc`)
      3. ensures image availability and freshness
      4. starts the container
      5. monitors health metrics until exit
      6. captures logs and destroys the container
    """

    EPHEMERAL_LABEL = "ironcore.managed"
    CONTAINER_PREFIX = "ironcore_sb"
    _IMAGE_PATTERN = re.compile(r"^[a-zA-Z0-9./:_-]+$")
    _SKILL_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")
    _SHELL_METACHAR_PATTERN = re.compile(r"(\|\||&&|;|`|\$\(|\n)")
    _IMAGE_INJECTION_PATTERN = re.compile(r"[\s;&|`$()]")

    def __init__(
        self,
        docker_base_url: Optional[str] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        if not _DOCKER_AVAILABLE:
            raise ImportError(
                "The 'docker' package is required for SandboxEngine. "
                "Install it with: pip install docker"
            )

        try:
            self._client = (
                docker.from_env()
                if docker_base_url is None
                else docker.DockerClient(base_url=docker_base_url)
            )
            self._client.ping()
        except DockerException as exc:
            raise ConnectionError(
                "Cannot connect to Docker daemon. Ensure Docker is running. "
                f"Details: {exc}"
            ) from exc

        self._event_bus = event_bus
        self._active_containers: Dict[str, Container] = {}
        self._image_cache: Dict[str, str] = {}
        logger.info("[SandboxEngine] Connected to Docker daemon.")

    async def spawn_and_execute(
        self,
        skill_name: str,
        command: str,
        policy: Optional[SandboxPolicy] = None,
    ) -> ExecutionResult:
        """
        Core isolation primitive: validate -> spawn -> monitor -> capture -> destroy.
        """
        effective_policy = policy or SandboxPolicy()
        validation = self._validate_execution_context(skill_name, command, effective_policy)
        if not validation.valid:
            raise SandboxValidationError(validation.violations)

        runtime_used = await self._resolve_runtime(effective_policy.runtime)
        image_digest = await self._ensure_image(effective_policy.image, effective_policy.pull_if_missing)
        image_digest = await self._check_image_freshness(
            image_name=effective_policy.image,
            pull_if_missing=effective_policy.pull_if_missing,
            cached_digest=image_digest,
        )

        container_name = f"{self.CONTAINER_PREFIX}_{skill_name}_{uuid.uuid4().hex[:8]}"
        start_time = time.monotonic()
        container: Optional[Container] = None
        monitor_task: Optional[asyncio.Task[List[ContainerHealthMetrics]]] = None

        logger.info(
            "[SandboxEngine] Spawning container=%s runtime=%s net=%s mem=%sMB timeout=%ss",
            container_name,
            runtime_used.value,
            effective_policy.network.value,
            effective_policy.max_memory_mb,
            effective_policy.max_execution_seconds,
        )

        try:
            run_kwargs = self._build_run_kwargs(
                container_name=container_name,
                skill_name=skill_name,
                command=command,
                policy=effective_policy,
                runtime_used=runtime_used,
            )
            loop = asyncio.get_running_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._client.containers.run(**run_kwargs),
            )
            self._active_containers[container_name] = container

            monitor_task = asyncio.create_task(
                self._monitor_container(
                    container=container,
                    memory_limit_mb=effective_policy.max_memory_mb,
                )
            )

            exit_code, timed_out = await self._wait_for_completion(
                container=container,
                timeout_seconds=effective_policy.max_execution_seconds,
            )

            health_metrics = await self._collect_health_metrics(monitor_task)
            stdout, stderr = await self._capture_logs(container)
            elapsed = time.monotonic() - start_time
            peak_memory_mb = max((metric.memory_mb for metric in health_metrics), default=0.0)

            result = ExecutionResult(
                container_id=container.id,
                container_short=container.short_id,
                skill_name=skill_name,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                execution_time_s=elapsed,
                timed_out=timed_out,
                image_used=effective_policy.image,
                health_metrics=health_metrics,
                peak_memory_mb=peak_memory_mb,
                image_digest=image_digest,
                runtime_used=runtime_used,
                security_violations=validation.violations,
            )
            logger.info("[SandboxEngine] %s", result.summary())
            return result
        except DockerException as exc:
            logger.exception("[SandboxEngine] Docker error for skill=%s: %s", skill_name, exc)
            raise RuntimeError(f"Sandbox execution failed for skill '{skill_name}': {exc}") from exc
        finally:
            if monitor_task is not None and not monitor_task.done():
                monitor_task.cancel()
                await self._collect_health_metrics(monitor_task)
            if container is not None:
                await self._destroy_container(container, container_name)

    @asynccontextmanager
    async def scoped_sandbox(
        self,
        skill_name: str,
        policy: Optional[SandboxPolicy] = None,
    ) -> AsyncGenerator["SandboxEngine", None]:
        """Yield this engine and purge the scoped skill containers on exit."""
        del policy
        try:
            yield self
        finally:
            await self.purge_skill(skill_name)

    async def purge_skill(self, skill_name: str) -> int:
        """Destroy all containers associated with a specific skill label."""
        loop = asyncio.get_running_loop()
        containers = await loop.run_in_executor(
            None,
            lambda: self._client.containers.list(
                all=True,
                filters={"label": f"ironcore.skill={skill_name}"},
            ),
        )
        count = 0
        for current in containers:
            try:
                await loop.run_in_executor(None, lambda c=current: c.remove(force=True))
                count += 1
            except DockerException as exc:
                logger.warning("[SandboxEngine] Could not purge container=%s: %s", current.short_id, exc)
        self._active_containers = {
            key: value
            for key, value in self._active_containers.items()
            if not key.startswith(f"{self.CONTAINER_PREFIX}_{skill_name}_")
        }
        logger.info("[SandboxEngine] Purged %s container(s) for skill=%s", count, skill_name)
        return count

    async def purge_all(self) -> int:
        """Emergency cleanup for every container managed by IronCore."""
        loop = asyncio.get_running_loop()
        containers = await loop.run_in_executor(
            None,
            lambda: self._client.containers.list(
                all=True,
                filters={"label": f"{self.EPHEMERAL_LABEL}=true"},
            ),
        )
        count = 0
        for current in containers:
            try:
                await loop.run_in_executor(None, lambda c=current: c.remove(force=True))
                count += 1
            except DockerException as exc:
                logger.warning("[SandboxEngine] Could not purge container=%s: %s", current.short_id, exc)
        self._active_containers.clear()
        logger.info("[SandboxEngine] Emergency purge removed %s container(s)", count)
        return count

    def close(self) -> None:
        """Close the underlying Docker client connection."""
        self._client.close()
        logger.info("[SandboxEngine] Docker client connection closed.")

    def _validate_execution_context(
        self,
        skill_name: str,
        command: str,
        policy: SandboxPolicy,
    ) -> ValidationResult:
        """
        Reject suspicious execution requests before Docker is even touched.
        """
        violations: List[str] = []

        if not self._SKILL_PATTERN.fullmatch(skill_name):
            violations.append("skill_name contains unsupported characters")

        if not self._IMAGE_PATTERN.fullmatch(policy.image) or self._IMAGE_INJECTION_PATTERN.search(policy.image):
            violations.append("image contains invalid or injectable characters")

        dangerous_rule = DangerousArgPatternRule(
            patterns=[
                ("command", r"(\.\./|os\.system|subprocess|__import__|exec\s*\()"),
            ]
        )
        dangerous_result = dangerous_rule.evaluate(
            tool_name="sandbox_exec",
            args={"command": command},
            context={},
        )
        if dangerous_result.verdict == PolicyVerdict.DENY:
            violations.append(dangerous_result.reason)

        if self._SHELL_METACHAR_PATTERN.search(command):
            violations.append("command contains blocked shell metacharacters")

        return ValidationResult(valid=not violations, violations=violations)

    def _build_run_kwargs(
        self,
        container_name: str,
        skill_name: str,
        command: str,
        policy: SandboxPolicy,
        runtime_used: RuntimeType,
    ) -> Dict[str, Any]:
        """Translate SandboxPolicy into docker-py containers.run() kwargs."""
        tmpfs = {directory: "size=64m,noexec" for directory in policy.writable_dirs}
        environment = {
            "IRONCORE_SKILL": skill_name,
            "PYTHONDONTWRITEBYTECODE": "1",
            **policy.extra_env,
        }

        return {
            "image": policy.image,
            "command": command,
            "name": container_name,
            "runtime": runtime_used.value,
            "network_mode": policy.network.value,
            "read_only": policy.readonly_root,
            "tmpfs": tmpfs,
            "mem_limit": f"{policy.max_memory_mb}m",
            "memswap_limit": f"{policy.max_memory_mb}m",
            "cpu_quota": policy.max_cpu_quota,
            "cpu_period": 100_000,
            "cap_drop": policy.drop_capabilities,
            "security_opt": ["no-new-privileges"],
            "environment": environment,
            "detach": True,
            "remove": False,
            "labels": {
                self.EPHEMERAL_LABEL: "true",
                "ironcore.skill": skill_name,
                "ironcore.container": container_name,
                "ironcore.runtime": runtime_used.value,
            },
        }

    async def _resolve_runtime(self, requested_runtime: RuntimeType) -> RuntimeType:
        """Use gVisor if available; otherwise fall back to the default Docker runtime."""
        if requested_runtime == RuntimeType.GVISOR and not GVisorAvailabilityChecker.is_available():
            logger.warning("[SandboxEngine] gVisor unavailable. Falling back to runc.")
            await self._publish_event(
                event_type="sandbox.runtime_fallback",
                payload={
                    "requested_runtime": requested_runtime.value,
                    "runtime_used": RuntimeType.DOCKER.value,
                },
            )
            return RuntimeType.DOCKER
        return requested_runtime

    async def _ensure_image(self, image_name: str, pull_if_missing: bool) -> Optional[str]:
        """Ensure an image is available locally and return its current digest if known."""
        loop = asyncio.get_running_loop()
        try:
            image = await loop.run_in_executor(None, lambda: self._client.images.get(image_name))
        except ImageNotFound:
            if not pull_if_missing:
                raise RuntimeError(f"Image '{image_name}' not found locally and pull_if_missing=False.")
            logger.info("[SandboxEngine] Pulling missing image=%s", image_name)
            image = await loop.run_in_executor(None, lambda: self._client.images.pull(image_name))
        digest = self._extract_digest(image)
        if digest:
            self._image_cache[image_name] = digest
        return digest

    async def _check_image_freshness(
        self,
        image_name: str,
        pull_if_missing: bool,
        cached_digest: Optional[str],
    ) -> Optional[str]:
        """
        Compare the cached/local digest with registry metadata and auto-refresh when it changes.
        """
        local_digest = cached_digest or self._image_cache.get(image_name)
        loop = asyncio.get_running_loop()
        try:
            registry_data = await loop.run_in_executor(
                None,
                lambda: self._client.images.get_registry_data(image_name),
            )
        except DockerException as exc:
            logger.debug("[SandboxEngine] Registry digest lookup skipped for image=%s: %s", image_name, exc)
            return local_digest

        remote_digest = self._extract_registry_digest(registry_data)
        if not remote_digest:
            return local_digest

        cached = self._image_cache.get(image_name)
        if cached and cached != remote_digest:
            logger.warning(
                "[SandboxEngine] Image digest changed for %s: cached=%s remote=%s",
                image_name,
                cached,
                remote_digest,
            )
            if pull_if_missing:
                image = await loop.run_in_executor(None, lambda: self._client.images.pull(image_name))
                local_digest = self._extract_digest(image) or remote_digest
            else:
                local_digest = remote_digest
            self._image_cache[image_name] = local_digest
            await self._publish_event(
                event_type="sandbox.image_updated",
                payload={"image": image_name, "digest": local_digest},
            )
            return local_digest

        self._image_cache[image_name] = remote_digest
        return remote_digest

    async def _monitor_container(
        self,
        container: Container,
        memory_limit_mb: int,
        interval: float = 1.0,
    ) -> List[ContainerHealthMetrics]:
        """Continuously collect container metrics until cancelled or the container disappears."""
        metrics: List[ContainerHealthMetrics] = []
        loop = asyncio.get_running_loop()

        try:
            while True:
                stats = await loop.run_in_executor(None, lambda: container.stats(stream=False))
                metric = self._parse_health_metrics(stats, getattr(container, "status", "unknown"))
                metrics.append(metric)

                if metric.memory_mb > memory_limit_mb * 0.9:
                    await self._publish_event(
                        event_type="sandbox.memory_warning",
                        payload={
                            "container_id": getattr(container, "id", ""),
                            "memory_mb": metric.memory_mb,
                            "memory_percent": metric.memory_percent,
                        },
                    )

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return metrics
        except (DockerException, APIError) as exc:
            logger.debug("[SandboxEngine] Health monitor stopped for container=%s: %s", container.short_id, exc)
            return metrics

    async def _wait_for_completion(
        self,
        container: Container,
        timeout_seconds: int,
    ) -> tuple[int, bool]:
        """Wait for container exit with a hard timeout."""
        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, container.wait),
                timeout=float(timeout_seconds),
            )
            return int(result.get("StatusCode", 0)), False
        except asyncio.TimeoutError:
            logger.warning(
                "[SandboxEngine] Container %s exceeded %ss; killing.",
                container.short_id,
                timeout_seconds,
            )
            try:
                await loop.run_in_executor(None, container.kill)
            except DockerException as exc:
                logger.debug("[SandboxEngine] Container kill failed after timeout: %s", exc)
            return -1, True

    async def _capture_logs(self, container: Container) -> tuple[str, str]:
        """Capture stdout and stderr from an exited container."""
        loop = asyncio.get_running_loop()
        raw_stdout = await loop.run_in_executor(
            None,
            lambda: container.logs(stdout=True, stderr=False),
        )
        raw_stderr = await loop.run_in_executor(
            None,
            lambda: container.logs(stdout=False, stderr=True),
        )
        return (
            raw_stdout.decode("utf-8", errors="replace"),
            raw_stderr.decode("utf-8", errors="replace"),
        )

    async def _destroy_container(self, container: Container, name: str) -> None:
        """Force-remove a container and clean tracking state."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: container.remove(force=True))
        except NotFound:
            logger.debug("[SandboxEngine] Container already removed: %s", container.short_id)
        except DockerException as exc:
            logger.error("[SandboxEngine] Failed to remove container=%s: %s", container.short_id, exc)
        finally:
            self._active_containers.pop(name, None)

    async def _collect_health_metrics(
        self,
        monitor_task: asyncio.Task[List[ContainerHealthMetrics]],
    ) -> List[ContainerHealthMetrics]:
        """Drain the health monitor task safely."""
        if not monitor_task.done():
            monitor_task.cancel()
        try:
            return await monitor_task
        except asyncio.CancelledError:
            return []

    async def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish sandbox events when an EventBus is available."""
        if self._event_bus is None:
            return
        await self._event_bus.publish(Event(event_type=event_type, payload=payload))

    @staticmethod
    def _parse_health_metrics(stats: Dict[str, Any], status: str) -> ContainerHealthMetrics:
        """Convert raw Docker stats into normalized metrics."""
        cpu_delta = (
            stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            - stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
        )
        system_delta = (
            stats.get("cpu_stats", {}).get("system_cpu_usage", 0)
            - stats.get("precpu_stats", {}).get("system_cpu_usage", 0)
        )
        online_cpus = stats.get("cpu_stats", {}).get("online_cpus") or 1
        cpu_percent = 0.0
        if system_delta > 0 and cpu_delta >= 0:
            cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0

        memory_usage = float(stats.get("memory_stats", {}).get("usage", 0))
        memory_limit = float(stats.get("memory_stats", {}).get("limit", 0)) or 1.0
        memory_mb = memory_usage / (1024 * 1024)
        memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit else 0.0

        networks = stats.get("networks", {})
        network_rx = sum(int(network.get("rx_bytes", 0)) for network in networks.values())
        network_tx = sum(int(network.get("tx_bytes", 0)) for network in networks.values())
        pids = int(stats.get("pids_stats", {}).get("current", 0))

        return ContainerHealthMetrics(
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
            memory_percent=memory_percent,
            pids=pids,
            network_rx_bytes=network_rx,
            network_tx_bytes=network_tx,
            status=status,
        )

    @staticmethod
    def _extract_digest(image: Any) -> Optional[str]:
        """Best-effort extraction of the local image digest."""
        attrs = getattr(image, "attrs", {}) or {}
        repo_digests = attrs.get("RepoDigests") or []
        if repo_digests:
            digest = str(repo_digests[0]).split("@", maxsplit=1)
            if len(digest) == 2:
                return digest[1]

        identifier = attrs.get("Id")
        if isinstance(identifier, str):
            return identifier
        return None

    @staticmethod
    def _extract_registry_digest(registry_data: Any) -> Optional[str]:
        """Best-effort extraction of a registry digest from docker SDK metadata."""
        attrs = getattr(registry_data, "attrs", {}) or {}
        descriptor = attrs.get("Descriptor", {})
        digest = descriptor.get("digest")
        if isinstance(digest, str):
            return digest

        identifier = getattr(registry_data, "id", None)
        if isinstance(identifier, str):
            return identifier
        return None


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

    async def _demo() -> None:
        try:
            engine = SandboxEngine()
        except (ImportError, ConnectionError) as exc:
            logger.error("Cannot start SandboxEngine: %s", exc)
            return

        policy = SandboxPolicy(
            image="python:3.11-alpine",
            network=NetworkPolicy.NONE,
            runtime=RuntimeType.GVISOR,
            max_memory_mb=64,
            max_execution_seconds=10,
        )

        try:
            result = await engine.spawn_and_execute(
                skill_name="demo_skill",
                command="python -c 'print(123)'",
                policy=policy,
            )
            logger.info("Execution result: %s", result.to_dict())
        except SandboxValidationError as exc:
            logger.error("Validation blocked execution: %s", exc)
        finally:
            engine.close()

    asyncio.run(_demo())
