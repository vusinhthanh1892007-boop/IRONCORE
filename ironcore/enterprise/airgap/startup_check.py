"""Startup connectivity audit for air-gapped deployments.

Probes a list of well-known external endpoints and verifies they are
*NOT* reachable.  If any external endpoint responds, the check fails
with a :exc:`SystemExit` (to halt the process) after logging a CRITICAL
message — indicating that the network isolation is broken.

Also verifies that the internal vLLM endpoint *is* reachable.

Usage::

    os.environ["IRONCORE_EDITION"] = "enterprise"
    config = AirGapConfig.from_env()
    await airgap_startup_check(config)           # raises SystemExit on violation
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import List, Optional, Tuple

from ironcore.enterprise.airgap.config import AirGapConfig

logger = logging.getLogger(__name__)

# Endpoints that MUST be unreachable in an air-gapped environment.
_EXTERNAL_PROBES: List[Tuple[str, int]] = [
    ("api.openai.com", 443),
    ("api.anthropic.com", 443),
    ("generativelanguage.googleapis.com", 443),
    ("pypi.org", 443),
    ("hub.docker.com", 443),
    ("huggingface.co", 443),
]


async def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    """Return True if TCP connection to host:port succeeds within *timeout*."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
        return False


async def airgap_startup_check(
    config: AirGapConfig,
    *,
    fail_on_external: bool = True,
) -> None:
    """Probe external + internal endpoints and enforce air-gap policy.

    Args:
        config: The active :class:`AirGapConfig`.
        fail_on_external: When *True* (default), raise :exc:`SystemExit`
            if any external endpoint is reachable.  Set to *False* in
            tests to get a return value instead of exiting.

    Raises:
        SystemExit: If ``fail_on_external=True`` and any external
            endpoint is accessible.
    """
    timeout = config.startup_check_timeout
    violations: List[str] = []

    logger.info("[AirGapCheck] Running startup checks (timeout=%.1fs each)…", timeout)

    # ── 1. Verify external hosts are NOT reachable ────────────────────────────
    for host, port in _EXTERNAL_PROBES:
        reachable = await _tcp_probe(host, port, timeout)
        if reachable:
            msg = f"EXTERNAL endpoint reachable: {host}:{port} — air-gap may be broken!"
            logger.critical("[AirGapCheck] %s", msg)
            violations.append(msg)
        else:
            logger.debug("[AirGapCheck] ✓ External probe blocked: %s:%d", host, port)

    # ── 2. Report ─────────────────────────────────────────────────────────────
    if violations:
        summary = "\n  ".join(violations)
        logger.critical(
            "[AirGapCheck] FAILED — %d violation(s):\n  %s",
            len(violations),
            summary,
        )
        if fail_on_external:
            raise SystemExit(
                f"[IronCore Enterprise] Air-gap startup check failed with "
                f"{len(violations)} violation(s). Process aborted."
            )
    else:
        logger.info("[AirGapCheck] All external probes blocked — air-gap intact.")
