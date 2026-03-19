"""Background worker entrypoint for Docker Compose deployments."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from ironcore.core.engine import IronCoreEngine
from ironcore.lsp.bridge import LSPBridge

logger = logging.getLogger(__name__)


class WorkerService:
    """Minimal long-running worker process for background agent execution."""

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._lsp_bridge = LSPBridge()

    async def run(self) -> None:
        """Start the worker loop and optionally process a boot prompt."""
        loop = asyncio.get_running_loop()
        for signame in ("SIGINT", "SIGTERM"):
            if hasattr(signal, signame):
                loop.add_signal_handler(
                    getattr(signal, signame),
                    self._stop_event.set,
                )

        prompt = os.environ.get("IRONCORE_WORKER_PROMPT", "").strip()
        interval_seconds = float(os.environ.get("IRONCORE_WORKER_HEARTBEAT_SECONDS", "30"))

        try:
            if prompt:
                await self._run_boot_prompt(prompt)

            while not self._stop_event.is_set():
                logger.info("[Worker] Heartbeat | status=idle")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                except asyncio.TimeoutError:
                    continue
        finally:
            await self._lsp_bridge.close()

    async def _run_boot_prompt(self, prompt: str) -> None:
        """Execute one startup prompt for smoke testing or batch workloads."""
        engine = IronCoreEngine(max_iterations=int(os.environ.get("IRONCORE_WORKER_MAX_ITERATIONS", "5")))
        self._lsp_bridge.register_tools(engine)
        history = await engine.run_loop(prompt)
        logger.info("[Worker] Boot prompt completed | history_items=%s", len(history))


async def _main() -> None:
    logging.basicConfig(
        level=os.environ.get("IRONCORE_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    await WorkerService().run()


if __name__ == "__main__":
    asyncio.run(_main())
