"""Async JSON-RPC client for Language Server Protocol over stdio."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LSPClient:
    """Manage a subprocess-based LSP server speaking JSON-RPC over stdio."""

    def __init__(
        self,
        server_command: Optional[List[str]] = None,
        root_path: Optional[Path] = None,
    ) -> None:
        self._server_command = server_command or ["pyright-langserver", "--stdio"]
        self._root_path = (root_path or Path.cwd()).resolve()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future[Any]] = {}
        self._notification_subscribers: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
        self._started = False
        self._initializing = False

    async def start(self) -> None:
        """Launch the language server and perform the initialize handshake."""
        if self._started:
            return

        executable = shutil.which(self._server_command[0])
        if executable is None:
            raise FileNotFoundError(
                f"LSP server executable '{self._server_command[0]}' not found in PATH."
            )

        command = [executable, *self._server_command[1:]]
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_messages())
        self._initializing = True
        try:
            await self.send_request(
                "initialize",
                {
                    "processId": None,
                    "rootUri": self._root_path.as_uri(),
                    "capabilities": {
                        "textDocument": {
                            "publishDiagnostics": {
                                "relatedInformation": True,
                            }
                        }
                    },
                },
            )
            self._started = True
            await self.send_notification("initialized", {})
            logger.info("[LSPClient] Started server=%s", self._server_command[0])
        finally:
            self._initializing = False

    async def send_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send a JSON-RPC request and await its response."""
        if not self._started and not self._initializing:
            await self.start()
        self._request_id += 1
        request_id = self._request_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[request_id] = future
        await self._send_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        return await future

    async def send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification without waiting for a response."""
        if not self._started and method != "initialized":
            await self.start()
        await self._send_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def subscribe_notification(self, method: str) -> "asyncio.Queue[Dict[str, Any]]":
        """Subscribe to a server notification stream."""
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._notification_subscribers.setdefault(method, []).append(queue)
        return queue

    async def close(self) -> None:
        """Gracefully shut down the language server subprocess."""
        if self._process is None:
            return

        try:
            if self._started:
                await self.send_request("shutdown", {})
                await self.send_notification("exit", {})
        except Exception as exc:
            logger.debug("[LSPClient] Graceful shutdown failed: %s", exc)

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()

        self._process = None
        self._reader_task = None
        self._started = False

    async def _send_message(self, payload: Dict[str, Any]) -> None:
        """Serialize and write one JSON-RPC message to stdin."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("LSP process stdin is unavailable.")

        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self._process.stdin.write(header + body)
        await self._process.stdin.drain()

    async def _read_messages(self) -> None:
        """Continuously parse JSON-RPC messages from stdout."""
        if self._process is None or self._process.stdout is None:
            return

        try:
            while True:
                message = await self._read_single_message()
                if message is None:
                    break
                await self._route_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[LSPClient] Reader loop crashed: %s", exc)
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(exc)
            self._pending_requests.clear()

    async def _read_single_message(self) -> Optional[Dict[str, Any]]:
        """Read exactly one JSON-RPC frame."""
        assert self._process is not None and self._process.stdout is not None

        headers: Dict[str, str] = {}
        while True:
            line = await self._process.stdout.readline()
            if not line:
                return None
            if line == b"\r\n":
                break
            name, _, value = line.decode("ascii").partition(":")
            headers[name.strip().lower()] = value.strip()

        content_length = int(headers["content-length"])
        body = await self._process.stdout.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    async def _route_message(self, message: Dict[str, Any]) -> None:
        """Deliver responses to futures and notifications to subscribers."""
        if "id" in message and "method" not in message:
            request_id = int(message["id"])
            future = self._pending_requests.pop(request_id, None)
            if future is None or future.done():
                return
            if "error" in message:
                future.set_exception(RuntimeError(str(message["error"])))
            else:
                future.set_result(message.get("result"))
            return

        method = message.get("method")
        if method is None:
            return
        for queue in self._notification_subscribers.get(method, []):
            await queue.put(message)
