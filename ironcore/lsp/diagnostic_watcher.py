"""Diagnostic subscription and waiting helpers for LSP notifications."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ironcore.lsp.client import LSPClient

logger = logging.getLogger(__name__)


class Position(BaseModel):
    """LSP position model."""

    line: int
    character: int


class Range(BaseModel):
    """LSP range model."""

    start: Position
    end: Position


class Diagnostic(BaseModel):
    """Normalized publishDiagnostics item."""

    severity: int = 0
    code: str | int | None = None
    message: str
    range: Range
    source: str | None = None


class DiagnosticWatcher:
    """Track and await diagnostics published by an LSP server."""

    def __init__(self, client: LSPClient) -> None:
        self._client = client
        self._queue = client.subscribe_notification("textDocument/publishDiagnostics")
        self._listener_task: asyncio.Task[None] | None = None
        self._latest: Dict[str, List[Diagnostic]] = {}
        self._waiters: Dict[str, List[asyncio.Future[List[Diagnostic]]]] = {}

    def start(self) -> None:
        """Ensure the background diagnostic listener is running."""
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    async def wait_for_diagnostics(self, uri: str, timeout: float = 3.0) -> List[Diagnostic]:
        """Wait for the next diagnostics event for a document or return the latest on timeout."""
        self.start()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[List[Diagnostic]] = loop.create_future()
        self._waiters.setdefault(uri, []).append(future)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return list(self._latest.get(uri, []))
        finally:
            waiters = self._waiters.get(uri, [])
            self._waiters[uri] = [item for item in waiters if item is not future]

    @staticmethod
    def has_errors(diagnostics: List[Diagnostic]) -> bool:
        """Return True when at least one diagnostic severity is Error."""
        return any(diagnostic.severity == 1 for diagnostic in diagnostics)

    async def close(self) -> None:
        """Stop the background listener."""
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

    async def _listen(self) -> None:
        """Consume publishDiagnostics notifications and wake pending waiters."""
        try:
            while True:
                message = await self._queue.get()
                params = message.get("params", {})
                uri = params.get("uri", "")
                diagnostics = [
                    Diagnostic.model_validate(item)
                    for item in params.get("diagnostics", [])
                ]
                self._latest[uri] = diagnostics
                for waiter in self._waiters.pop(uri, []):
                    if not waiter.done():
                        waiter.set_result(diagnostics)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[DiagnosticWatcher] Listener crashed: %s", exc)
