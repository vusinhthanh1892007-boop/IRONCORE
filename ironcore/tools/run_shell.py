"""
IronCore Tool: Shell Execution
==============================
Execute shell commands in a sandboxed environment.
Uses IronCore's SandboxEngine for isolation when available,
falls back to subprocess with resource limits.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from typing import Optional

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_OUTPUT_SIZE = 100_000  # 100 KB


async def _run_sandboxed(command: str, timeout: int, workdir: Optional[str]) -> dict:
    """Execute via IronCore SandboxEngine (Docker isolation)."""
    try:
        from ironcore.sandbox.engine import SandboxEngine, SandboxPolicy, NetworkPolicy

        engine = SandboxEngine()
        policy = SandboxPolicy(
            image="python:3.12-slim",
            network=NetworkPolicy.INTERNAL,
            readonly_root=False,
            writable_dirs=["/tmp", "/workspace"],
            max_execution_seconds=timeout,
            max_memory_mb=512,
            drop_capabilities=["ALL"],
        )
        result = await engine.execute(
            command=["sh", "-c", command],
            policy=policy,
        )
        return {
            "stdout": (result.stdout or "")[:_MAX_OUTPUT_SIZE],
            "stderr": (result.stderr or "")[:_MAX_OUTPUT_SIZE],
            "exit_code": result.exit_code,
            "sandbox": True,
        }
    except ImportError:
        logger.debug("[run_shell] SandboxEngine not available, using subprocess")
        return await _run_subprocess(command, timeout, workdir)
    except Exception as exc:
        logger.warning("[run_shell] Sandbox failed, falling back to subprocess: %s", exc)
        return await _run_subprocess(command, timeout, workdir)


async def _run_subprocess(command: str, timeout: int, workdir: Optional[str]) -> dict:
    """Execute via asyncio subprocess with resource limits."""
    cwd = workdir if workdir and os.path.isdir(workdir) else None

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1,
            "sandbox": False,
        }

    return {
        "stdout": (stdout_bytes or b"").decode("utf-8", errors="replace")[:_MAX_OUTPUT_SIZE],
        "stderr": (stderr_bytes or b"").decode("utf-8", errors="replace")[:_MAX_OUTPUT_SIZE],
        "exit_code": proc.returncode,
        "sandbox": False,
    }


@skill(
    name="run_shell",
    version="1.0.0",
    description="Execute a shell command and return stdout/stderr. Uses sandbox isolation when available.",
    long_description=(
        "Run arbitrary shell commands. When Docker is available, commands run in "
        "an isolated container via SandboxEngine. Falls back to subprocess with timeout limits."
    ),
    author="brain",
    tags=["shell", "system", "execution"],
    risk_level=RiskLevel.HIGH,
    requires_sandbox=True,
    requires_network=False,
    estimated_latency_ms=5000.0,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(name="command", type="string", description="Shell command to execute", required=True),
        SkillParameterSchema(name="timeout", type="int", description="Timeout in seconds (max 120)", required=False, default=30),
        SkillParameterSchema(name="workdir", type="string", description="Working directory path", required=False),
    ],
)
async def run_shell(command: str, timeout: int = 30, workdir: Optional[str] = None) -> str:
    """Execute a shell command with isolation."""
    timeout = max(1, min(120, timeout))
    result = await _run_sandboxed(command, timeout, workdir)
    return json.dumps(result, ensure_ascii=False)
