from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ironcore.lsp.diagnostic_watcher import Diagnostic, Position, Range
from ironcore.lsp.document_manager import DocumentManager
from ironcore.lsp.safe_editor import SafeEditor


class FakeLSPClient:
    def __init__(self) -> None:
        self.notifications: List[Dict[str, Any]] = []
        self.started = False
        self._queues: Dict[str, asyncio.Queue[Dict[str, Any]]] = {}

    async def start(self) -> None:
        self.started = True

    async def send_notification(self, method: str, params: Dict[str, Any]) -> None:
        self.notifications.append({"method": method, "params": params})

    def subscribe_notification(self, method: str) -> asyncio.Queue[Dict[str, Any]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._queues[method] = queue
        return queue


class FakeDiagnosticWatcher:
    def __init__(self, diagnostics: List[Diagnostic]) -> None:
        self._diagnostics = diagnostics
        self.started = False

    def start(self) -> None:
        self.started = True

    async def wait_for_diagnostics(self, uri: str, timeout: float = 3.0) -> List[Diagnostic]:
        del uri, timeout
        return list(self._diagnostics)

    @staticmethod
    def has_errors(diagnostics: List[Diagnostic]) -> bool:
        return any(diagnostic.severity == 1 for diagnostic in diagnostics)


def _syntax_error() -> Diagnostic:
    return Diagnostic(
        severity=1,
        message="SyntaxError",
        range=Range(
            start=Position(line=0, character=0),
            end=Position(line=0, character=1),
        ),
        source="pyright",
    )


@pytest.mark.asyncio
async def test_valid_edit_accepted(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.py"
    old_text = "value = 1\n"
    new_text = "value = 2\n"
    file_path.write_text(old_text, encoding="utf-8")

    client = FakeLSPClient()
    document_manager = DocumentManager(client)
    watcher = FakeDiagnosticWatcher([])
    editor = SafeEditor(client, document_manager, watcher)

    result = await editor.apply_safe_edit(str(file_path), old_text=old_text, new_text=new_text)

    assert result.success is True
    assert result.rolled_back is False
    assert file_path.read_text(encoding="utf-8") == new_text


@pytest.mark.asyncio
async def test_syntax_error_rolled_back(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.py"
    old_text = "value = 1\n"
    new_text = "value =\n"
    file_path.write_text(old_text, encoding="utf-8")

    client = FakeLSPClient()
    document_manager = DocumentManager(client)
    watcher = FakeDiagnosticWatcher([_syntax_error()])
    editor = SafeEditor(client, document_manager, watcher)

    result = await editor.apply_safe_edit(str(file_path), old_text=old_text, new_text=new_text)

    assert result.success is False
    assert result.rolled_back is True
    assert result.error is not None


@pytest.mark.asyncio
async def test_file_unchanged_after_rollback(tmp_path: Path) -> None:
    file_path = tmp_path / "rollback.py"
    original = "answer = 42\n"
    file_path.write_text(original, encoding="utf-8")

    client = FakeLSPClient()
    document_manager = DocumentManager(client)
    watcher = FakeDiagnosticWatcher([_syntax_error()])
    editor = SafeEditor(client, document_manager, watcher)

    await editor.apply_safe_edit(
        str(file_path),
        old_text=original,
        new_text="answer =\n",
    )

    assert file_path.read_text(encoding="utf-8") == original
