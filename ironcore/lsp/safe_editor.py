"""High-level safe editing workflow with automatic rollback on diagnostics."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from ironcore.lsp.diagnostic_watcher import Diagnostic, DiagnosticWatcher
from ironcore.lsp.document_manager import DocumentManager

logger = logging.getLogger(__name__)


class SafeEditResult(BaseModel):
    """Outcome of a syntax-safe edit transaction."""

    success: bool
    rolled_back: bool
    file_path: str
    uri: str
    diagnostics: List[Diagnostic] = Field(default_factory=list)
    diff: str = ""
    error: Optional[str] = None


class SafeEditor:
    """Apply text edits and revert automatically when diagnostics report errors."""

    def __init__(
        self,
        client,
        document_manager: DocumentManager,
        diagnostic_watcher: DiagnosticWatcher,
        diagnostics_timeout: float = 3.0,
    ) -> None:
        self._client = client
        self._document_manager = document_manager
        self._diagnostic_watcher = diagnostic_watcher
        self._diagnostics_timeout = diagnostics_timeout

    async def apply_safe_edit(
        self,
        file_path: str,
        old_text: str,
        new_text: str,
    ) -> SafeEditResult:
        """
        Apply an edit, wait for diagnostics, and rollback on syntax errors.
        """
        await self._client.start()
        self._diagnostic_watcher.start()

        path = Path(file_path).resolve()
        original_text = path.read_text(encoding="utf-8")
        if original_text != old_text:
            raise ValueError("File contents do not match the provided old_text.")

        uri = await self._document_manager.open_document(path)
        try:
            await self._document_manager.apply_edit(uri, old_text=original_text, new_text=new_text)
            diagnostics = await self._diagnostic_watcher.wait_for_diagnostics(
                uri,
                timeout=self._diagnostics_timeout,
            )
            diff = self._build_diff(original_text, new_text, str(path))

            if self._diagnostic_watcher.has_errors(diagnostics):
                await self._document_manager.apply_edit(uri, old_text=new_text, new_text=original_text)
                return SafeEditResult(
                    success=False,
                    rolled_back=True,
                    file_path=str(path),
                    uri=uri,
                    diagnostics=diagnostics,
                    diff=diff,
                    error="Diagnostics reported syntax or semantic errors. Changes rolled back.",
                )

            return SafeEditResult(
                success=True,
                rolled_back=False,
                file_path=str(path),
                uri=uri,
                diagnostics=diagnostics,
                diff=diff,
            )
        except Exception:
            if path.exists():
                path.write_text(original_text, encoding="utf-8")
            raise
        finally:
            await self._document_manager.close_document(uri)

    @staticmethod
    def _build_diff(old_text: str, new_text: str, file_path: str) -> str:
        """Return a unified diff between the original and edited content."""
        return "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=file_path,
                tofile=file_path,
            )
        )
