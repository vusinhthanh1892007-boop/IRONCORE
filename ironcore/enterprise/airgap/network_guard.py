"""Runtime network enforcer for air-gapped deployments.

Patches ``httpx`` (and optionally ``urllib.request``) at import time so that
any outbound HTTP call is checked against the configured CIDR allowlist before
it is allowed to proceed.  Unknown / external destinations raise
:exc:`NetworkViolationError` and are audit-logged.

Usage::

    os.environ["IRONCORE_EDITION"] = "enterprise"
    config = AirGapConfig.from_env()
    guard = AirGapNetworkGuard(config)
    guard.install()   # call once at process startup
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence
from unittest.mock import patch

from ironcore.enterprise.airgap.config import AirGapConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class NetworkViolationError(Exception):
    """Raised when an outbound connection targets an external address."""


class AirGapNetworkGuard:
    """Enforce network isolation at the Python HTTP-client layer.

    After :meth:`install` is called every ``httpx`` request goes through
    :meth:`_check_host` which resolves the destination and compares it
    against :attr:`_allowed_networks`.  External destinations are denied
    and logged.

    The guard is idempotent — calling :meth:`install` multiple times is safe.
    """

    _installed: bool = False

    def __init__(self, config: AirGapConfig) -> None:
        self._config = config
        self._allowed_networks: List[ipaddress.IPv4Network] = []
        for cidr in config.allowed_internal_cidrs:
            try:
                self._allowed_networks.append(
                    ipaddress.IPv4Network(cidr, strict=False)
                )
            except ValueError:
                logger.warning("[AirGapGuard] Invalid CIDR ignored: %s", cidr)

    # ── Public API ────────────────────────────────────────────────────────────

    def install(self) -> None:
        """Patch HTTP clients to enforce network isolation.

        Currently patches:
        - ``httpx.Client.send``
        - ``httpx.AsyncClient.send``
        """
        if AirGapNetworkGuard._installed:
            logger.debug("[AirGapGuard] Already installed — skipping.")
            return

        # Patch httpx if available. At import time httpx may not be installed;
        # we only patch if it is present so unit tests without httpx still work.
        try:
            import httpx

            original_sync_send = httpx.Client.send
            original_async_send = httpx.AsyncClient.send
            guard = self  # capture for closures

            def _patched_sync_send(
                self_client: Any, request: Any, **kwargs: Any
            ) -> Any:
                guard._check_host(str(request.url.host))
                return original_sync_send(self_client, request, **kwargs)

            async def _patched_async_send(
                self_client: Any, request: Any, **kwargs: Any
            ) -> Any:
                guard._check_host(str(request.url.host))
                return await original_async_send(self_client, request, **kwargs)

            httpx.Client.send = _patched_sync_send  # type: ignore[method-assign]
            httpx.AsyncClient.send = _patched_async_send  # type: ignore[method-assign]
            logger.info("[AirGapGuard] httpx patched.")
        except ImportError:
            logger.debug("[AirGapGuard] httpx not found — skipping patch.")

        AirGapNetworkGuard._installed = True
        logger.info(
            "[AirGapGuard] Installed | allowed_cidrs=%s",
            self._config.allowed_internal_cidrs,
        )

    def uninstall(self) -> None:
        """Remove patches (mainly for testing)."""
        try:
            import httpx

            # Remove by reloading the module-level originals if still reachable.
            # The simplest approach for tests is to reload httpx.
            import importlib

            importlib.reload(httpx)
            logger.info("[AirGapGuard] httpx unpatched (module reloaded).")
        except Exception:
            pass
        AirGapNetworkGuard._installed = False

    def is_allowed_host(self, host: str) -> bool:
        """Return True if *host* resolves to an internal IP."""
        if self._config.allow_external_network:
            return True
        try:
            ip = ipaddress.IPv4Address(socket.gethostbyname(host))
            return self._is_internal_ip(ip)
        except (socket.gaierror, ValueError, OSError):
            # Cannot resolve → deny
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_host(self, host: str) -> None:
        """Raise :exc:`NetworkViolationError` if *host* is external."""
        if not self.is_allowed_host(host):
            msg = (
                f"[AirGap] BLOCKED outbound connection to '{host}' — "
                "not in allowed internal CIDRs."
            )
            logger.critical(msg)
            raise NetworkViolationError(msg)

    def _is_internal_ip(self, ip: ipaddress.IPv4Address) -> bool:
        return any(ip in net for net in self._allowed_networks)
