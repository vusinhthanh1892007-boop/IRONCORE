"""High-level LSP bridge for safe code editing and engine tool registration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ironcore.core.engine import IronCoreEngine, RiskLevel, ToolDefinition
from ironcore.lsp.client import LSPClient
from ironcore.lsp.diagnostic_watcher import DiagnosticWatcher
from ironcore.lsp.document_manager import DocumentManager
from ironcore.lsp.safe_editor import SafeEditResult, SafeEditor

logger = logging.getLogger(__name__)


class LSPBridge:
    """Compose the low-level LSP client pieces into one safe-edit bridge."""

    def __init__(
        self,
        root_path: Optional[Path] = None,
        server_command: Optional[List[str]] = None,
        diagnostics_timeout: float = 3.0,
    ) -> None:
        self.client = LSPClient(server_command=server_command, root_path=root_path)
        self.diagnostic_watcher = DiagnosticWatcher(self.client)
        self.document_manager = DocumentManager(self.client)
        self.safe_editor = SafeEditor(
            client=self.client,
            document_manager=self.document_manager,
            diagnostic_watcher=self.diagnostic_watcher,
            diagnostics_timeout=diagnostics_timeout,
        )

    async def close(self) -> None:
        """Release background tasks and the language server subprocess."""
        await self.diagnostic_watcher.close()
        await self.client.close()

    def get_safe_code_edit_tool(self) -> ToolDefinition:
        """Build the ToolDefinition used by IronCoreEngine."""
        return ToolDefinition(
            name="safe_code_edit",
            handler=self.safe_editor.apply_safe_edit,
            risk_level=RiskLevel.MEDIUM,
            requires_sandbox=False,
            description="Edit source code safely and auto-rollback on syntax errors.",
        )

    def register_tools(self, engine: IronCoreEngine) -> None:
        """Register all LSP-backed tools with the core engine."""
        engine.register_tool(self.get_safe_code_edit_tool())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def _demo() -> None:
        bridge = LSPBridge(root_path=Path.cwd())
        engine = IronCoreEngine(max_iterations=1)
        bridge.register_tools(engine)
        logger.info("Registered tools: %s", engine.registered_tools)
        await bridge.close()

    asyncio.run(_demo())
