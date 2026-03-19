"""Phase 20 — CE Self-Healing LSP Code Engine.

SelfHealingEngine subscribes to DiagnosticWatcher and drives a repair loop:
  detect error → prompt LLM for fix → validate → backup + apply → re-check
  (up to max_retries per file, then escalate with a TODO comment)

CE feature — available in all editions.

Env vars:
    IRONCORE_SELF_HEALING_ENABLED=true
    IRONCORE_SELF_HEALING_AUTO_APPLY=false      # false = dry-run only
    IRONCORE_SELF_HEALING_MAX_RETRIES=3
    IRONCORE_SELF_HEALING_MODEL=claude-3-5-haiku-20241022
    IRONCORE_SELF_HEALING_BACKUP_ENABLED=true
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ironcore.lsp.diagnostic_watcher import Diagnostic, DiagnosticWatcher

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_ENABLED = os.environ.get("IRONCORE_SELF_HEALING_ENABLED", "true").lower() != "false"
_AUTO_APPLY = os.environ.get("IRONCORE_SELF_HEALING_AUTO_APPLY", "false").lower() == "true"
_MAX_RETRIES = int(os.environ.get("IRONCORE_SELF_HEALING_MAX_RETRIES", "3"))
_HEAL_MODEL = os.environ.get("IRONCORE_SELF_HEALING_MODEL", "claude-3-5-haiku-20241022")
_BACKUP_ENABLED = os.environ.get("IRONCORE_SELF_HEALING_BACKUP_ENABLED", "true").lower() != "false"

# Default excluded path fragments (never heal files in these directories)
_DEFAULT_EXCLUDED = [".venv", "__pycache__", "node_modules", ".git", ".tox", "dist", "build"]

# Security-sensitive patterns — never auto-apply fixes to lines matching these
_SECURITY_PATTERNS = [
    re.compile(r"password\s*=", re.I),
    re.compile(r"(api_?key|secret_?key|auth_?token)\s*=", re.I),
    re.compile(r"(subprocess|os\.system|eval|exec)\s*\(", re.I),
    re.compile(r"execute\s*\(\s*[\"']?\s*select.*?%s", re.I),
    re.compile(r"cursor\.execute\s*\(.*?%", re.I),
]

# ── Repair prompt ─────────────────────────────────────────────────────────────

_REPAIR_SYSTEM_PROMPT = """\
You are a Python code healer. You will receive:
1. A Python file with its full content
2. A list of type errors / syntax errors from Pyright / the Python parser

Your task: Output ONLY a unified diff (--- a/file +++ b/file) fixing all listed errors.
Rules:
- Fix ONLY the listed errors, nothing else
- Preserve all comments, docstrings, and unrelated code exactly
- Do not add imports unless strictly required by the fix
- Do not reformat code or change style
- If you cannot fix an error safely, add a comment: # HEALER: unable to fix: <error>
- If output is empty (no changes needed), output exactly: NO_CHANGES
"""


# ── Data models ───────────────────────────────────────────────────────────────

class HealingAttempt(BaseModel):
    """Record of one healing attempt for a single file."""

    file_path: str
    original_errors: List[Diagnostic] = Field(default_factory=list)
    proposed_fix: str = ""          # unified diff string
    applied_at: float = 0.0         # epoch timestamp; 0 = dry-run / not applied
    errors_after: List[Diagnostic] = Field(default_factory=list)
    success: bool = False
    retry_count: int = 0
    backup_path: str = ""
    skipped_security: bool = False


# ── SelfHealingEngine ─────────────────────────────────────────────────────────

class SelfHealingEngine:
    """
    Subscribe to DiagnosticWatcher and automatically repair Python files.

    Healing loop per file:
      1. Read file content
      2. Format diagnostic context → LLM "code repair" prompt
      3. Parse LLM response → unified diff
      4. Validate diff via ``ast.parse`` (syntax check on patched text)
      5. Backup + apply (if auto_apply=True)
      6. Wait for next diagnostic cycle; repeat up to max_retries
      7. If errors remain → insert TODO comment, mark attempt failed
    """

    def __init__(
        self,
        diagnostic_watcher: DiagnosticWatcher,
        llm_bridge: Any,            # LLMBridge — Any to avoid circular import
        workspace_root: str,
        max_retries: int = _MAX_RETRIES,
        auto_apply: bool = _AUTO_APPLY,
        backup_enabled: bool = _BACKUP_ENABLED,
        excluded_patterns: Optional[List[str]] = None,
        enabled: bool = _ENABLED,
    ) -> None:
        self._watcher = diagnostic_watcher
        self._llm = llm_bridge
        self._workspace_root = Path(workspace_root).resolve()
        self.max_retries = max_retries
        self.auto_apply = auto_apply
        self.backup_enabled = backup_enabled
        self.excluded_patterns: List[str] = (
            excluded_patterns if excluded_patterns is not None else list(_DEFAULT_EXCLUDED)
        )
        self.enabled = enabled
        self._report: Dict[str, List[HealingAttempt]] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to diagnostics and start the background healing loop. Non-blocking."""
        if not self.enabled or self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._healing_loop())

    async def stop(self) -> None:
        """Cancel the background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ── Core healing flow ──────────────────────────────────────────────────────

    async def heal_file(
        self,
        file_path: str,
        errors: List[Diagnostic],
    ) -> HealingAttempt:
        """
        Full healing flow for one file.
        Returns a HealingAttempt regardless of outcome.
        """
        attempt = HealingAttempt(
            file_path=file_path,
            original_errors=list(errors),
        )

        if self._is_excluded(file_path):
            logger.debug("[Healer] Skipping excluded path: %s", file_path)
            self._record(file_path, attempt)
            return attempt

        path = Path(file_path)
        if not path.is_file() or path.suffix != ".py":
            logger.debug("[Healer] Not a Python file, skipping: %s", file_path)
            self._record(file_path, attempt)
            return attempt

        content = path.read_text(encoding="utf-8")

        # Security gate — warn and skip if file contains sensitive patterns
        if self._has_security_patterns(content):
            logger.warning(
                "[Healer] Security-sensitive pattern detected in %s — skipping auto-fix.",
                file_path,
            )
            attempt.skipped_security = True
            self._record(file_path, attempt)
            return attempt

        # Build & send repair prompt
        proposed_diff = await self._request_fix(file_path, content, errors)
        attempt.proposed_fix = proposed_diff

        if not proposed_diff or proposed_diff.strip() == "NO_CHANGES":
            attempt.success = True
            self._record(file_path, attempt)
            return attempt

        # Validate the proposed diff
        try:
            patched = self._apply_diff(content, proposed_diff)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Healer] Diff apply failed for %s: %s", file_path, exc)
            self._add_todo_comment(path, errors)
            self._record(file_path, attempt)
            return attempt

        if not self._ast_valid(patched):
            logger.warning("[Healer] Proposed fix for %s fails AST validation; skipping.", file_path)
            self._add_todo_comment(path, errors)
            self._record(file_path, attempt)
            return attempt

        if not self.auto_apply:
            # Dry-run: do not touch disk
            attempt.success = True  # fix is ready but not applied
            self._record(file_path, attempt)
            return attempt

        # Backup + apply
        backup_path = self._backup_file(file_path) if self.backup_enabled else ""
        attempt.backup_path = backup_path
        path.write_text(patched, encoding="utf-8")
        attempt.applied_at = time.time()
        logger.info("[Healer] Applied fix to %s (backup: %s)", file_path, backup_path or "disabled")

        # Re-check: wait for fresh diagnostics
        uri = f"file://{path.resolve()}"
        fresh_errors = await self._watcher.wait_for_diagnostics(uri, timeout=2.0)
        error_diagnostics = [d for d in fresh_errors if d.severity == 1]
        attempt.errors_after = error_diagnostics
        attempt.success = len(error_diagnostics) == 0

        if not attempt.success:
            logger.warning(
                "[Healer] %d errors remain in %s after fix attempt.",
                len(error_diagnostics), file_path,
            )
            if attempt.retry_count >= self.max_retries:
                self._add_todo_comment(path, error_diagnostics)

        self._record(file_path, attempt)
        return attempt

    async def get_report(self) -> Dict[str, List[HealingAttempt]]:
        """Return the full healing history indexed by file path."""
        return dict(self._report)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _healing_loop(self) -> None:
        """Background task: listen for diagnostic events and trigger healing."""
        logger.info("[Healer] Background healing loop started.")
        while self._running:
            # Pull one entry from the watcher's internal event queue
            try:
                raw = await asyncio.wait_for(
                    self._watcher._queue.get(), timeout=5.0  # noqa: SLF001
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            uri: str = raw.get("uri", "")
            diagnostics_raw = raw.get("diagnostics", [])
            if not uri:
                continue

            from ironcore.lsp.diagnostic_watcher import Diagnostic, Range, Position  # noqa: PLC0415
            diags: List[Diagnostic] = [
                Diagnostic(**d) if isinstance(d, dict) else d
                for d in diagnostics_raw
            ]
            errors = [d for d in diags if d.severity == 1]
            if not errors:
                continue

            file_path = uri.removeprefix("file://")
            prev_attempts = self._report.get(file_path, [])
            retry_count = len([a for a in prev_attempts if not a.success])
            if retry_count >= self.max_retries:
                logger.debug("[Healer] Max retries reached for %s, skipping.", file_path)
                continue

            logger.info("[Healer] %d errors detected in %s — attempting heal.", len(errors), file_path)
            attempt = await self.heal_file(file_path, errors)
            attempt.retry_count = retry_count

    async def _request_fix(
        self,
        file_path: str,
        content: str,
        errors: List[Diagnostic],
    ) -> str:
        """Build the LLM prompt and call the bridge for a unified diff."""
        error_lines = []
        for d in errors:
            line = d.range.start.line + 1  # LSP is 0-based
            col = d.range.start.character + 1
            error_lines.append(f"  Line {line}, Col {col}: {d.message}")
        errors_text = "\n".join(error_lines)

        user_prompt = (
            f"File: {file_path}\n\n"
            f"```python\n{content}\n```\n\n"
            f"Errors to fix:\n{errors_text}"
        )

        try:
            from ironcore.core.llm_bridge import ModelConfig  # noqa: PLC0415

            response = await self._llm.call_llm(
                messages=[
                    {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                model_config=ModelConfig(
                    model_id=_HEAL_MODEL,
                    max_output_tokens=2048,
                ),
            )
            return response.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("[Healer] LLM request failed: %s", exc)
            return ""

    def _is_excluded(self, file_path: str) -> bool:
        """Return True if the file_path matches any excluded fragment."""
        p = str(Path(file_path).resolve())
        return any(fragment in p for fragment in self.excluded_patterns)

    @staticmethod
    def _has_security_patterns(content: str) -> bool:
        """Return True if content has security-sensitive patterns."""
        for pattern in _SECURITY_PATTERNS:
            if pattern.search(content):
                return True
        return False

    def _backup_file(self, file_path: str) -> str:
        """Copy file to <file>.bak.<ISO8601> and return the backup path."""
        src = Path(file_path)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup = src.with_suffix(f"{src.suffix}.bak.{ts}")
        backup.write_bytes(src.read_bytes())
        return str(backup)

    @staticmethod
    def _apply_diff(original: str, diff: str) -> str:
        """
        Apply a unified diff string to original text.
        Strips markdown fences if present, then patches line by line.
        """
        # Strip possible markdown code fences around the diff
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", diff.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip())

        # Use difflib.restore to reconstruct '+' lines; if that fails, try patch utility
        lines = cleaned.splitlines(keepends=True)
        patched_lines: List[str] = []
        orig_lines = original.splitlines(keepends=True)
        orig_idx = 0

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@ "):
                if line.startswith("@@ "):
                    # Parse hunk header: @@ -start,count +start,count @@
                    m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                    if m:
                        orig_start = int(m.group(1)) - 1
                        orig_idx = orig_start
                i += 1
                continue
            if line.startswith("+") and not line.startswith("+++"):
                patched_lines.append(line[1:])
                i += 1
            elif line.startswith("-") and not line.startswith("---"):
                orig_idx += 1
                i += 1
            elif line.startswith(" "):
                patched_lines.append(line[1:])
                orig_idx += 1
                i += 1
            else:
                # Non-diff line — pass through as context
                patched_lines.append(line)
                i += 1

        # If nothing was patched (diff parsing failed), raise so caller can handle
        if not patched_lines:
            raise ValueError("Empty patch result — diff parsing produced no output.")

        return "".join(patched_lines)

    @staticmethod
    def _ast_valid(source: str) -> bool:
        """Return True if source parses without SyntaxError."""
        try:
            ast.parse(source)
            return True
        except SyntaxError:
            return False

    @staticmethod
    def _add_todo_comment(path: Path, errors: List[Diagnostic]) -> None:
        """Prepend a TODO block to the file when all retries are exhausted."""
        messages = "; ".join(d.message for d in errors[:3])
        todo = f"# HEALER: unable to fix after max retries — {messages}\n"
        content = path.read_text(encoding="utf-8")
        if not content.startswith("# HEALER:"):
            path.write_text(todo + content, encoding="utf-8")

    def _record(self, file_path: str, attempt: HealingAttempt) -> None:
        self._report.setdefault(file_path, []).append(attempt)
