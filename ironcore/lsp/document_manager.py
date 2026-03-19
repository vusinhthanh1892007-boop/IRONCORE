"""Helpers for opening, editing, and closing LSP documents safely."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from pydantic import BaseModel, Field

from ironcore.lsp.client import LSPClient

logger = logging.getLogger(__name__)


class EditTransaction(BaseModel):
    """Record of one textDocument/didChange operation."""

    uri: str
    file_path: str
    version: int
    old_text: str
    new_text: str
    timestamp: float = Field(default_factory=lambda: __import__("time").time())


class _DocumentSnapshot(BaseModel):
    uri: str
    file_path: Path
    version: int
    language_id: str
    text: str


class DocumentManager:
    """Track open documents and mirror edits to disk plus the language server."""

    def __init__(self, client: LSPClient) -> None:
        self._client = client
        self._document_snapshots: Dict[str, _DocumentSnapshot] = {}

    async def open_document(self, file_path: Path) -> str:
        """Load a file from disk and send textDocument/didOpen."""
        path = file_path.resolve()
        text = path.read_text(encoding="utf-8")
        uri = path.as_uri()
        snapshot = _DocumentSnapshot(
            uri=uri,
            file_path=path,
            version=1,
            language_id=self._language_id_for_path(path),
            text=text,
        )
        self._document_snapshots[uri] = snapshot
        await self._client.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": snapshot.language_id,
                    "version": snapshot.version,
                    "text": text,
                }
            },
        )
        return uri

    async def apply_edit(self, uri: str, old_text: str, new_text: str) -> EditTransaction:
        """Write updated text to disk and notify the language server."""
        snapshot = self._document_snapshots[uri]
        if snapshot.text != old_text:
            raise ValueError("Document content diverged from the expected old_text.")

        snapshot.file_path.write_text(new_text, encoding="utf-8")
        next_version = snapshot.version + 1
        transaction = EditTransaction(
            uri=uri,
            file_path=str(snapshot.file_path),
            version=next_version,
            old_text=old_text,
            new_text=new_text,
        )
        self._document_snapshots[uri] = snapshot.model_copy(
            update={"text": new_text, "version": next_version}
        )
        await self._client.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": uri,
                    "version": next_version,
                },
                "contentChanges": [{"text": new_text}],
            },
        )
        return transaction

    async def close_document(self, uri: str) -> None:
        """Send textDocument/didClose and drop the in-memory snapshot."""
        snapshot = self._document_snapshots.pop(uri, None)
        if snapshot is None:
            return
        await self._client.send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": uri}},
        )

    def snapshot_text(self, uri: str) -> str:
        """Return the currently tracked document text."""
        return self._document_snapshots[uri].text

    @staticmethod
    def _language_id_for_path(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix in {".ts", ".tsx"}:
            return "typescript"
        if suffix == ".js":
            return "javascript"
        if suffix == ".json":
            return "json"
        return "plaintext"
