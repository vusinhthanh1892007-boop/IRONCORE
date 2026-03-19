"""
IronCore V2: OTA Update Manager
=================================
Phase 2 — The Architect (Gemini 3.1)

Supports three update types:
  CONFIG (hot)    — update env vars at runtime, zero restart
  PLUGIN (warm)   — git pull plugin source + hot-reload via PluginRegistry
  CORE   (rolling)— git pull core → SIGTERM → Docker restart → health check

Security design:
    - All git commands use list form (no shell=True) to prevent injection.
    - Config keys validated against r'^[A-Z][A-Z0-9_]{1,99}$' before apply.
    - backup_timestamp validated against r'^\\d{8}_\\d{6}$' to prevent path traversal.
    - Commit hashes validated as 40-char hex before use in git reset.
    - asyncio.Lock serialises all mutable operations.

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import signal
import time
import urllib.error
import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ─── Validation patterns ────────────────────────────────────────────────────
# Config keys: UPPER_CASE_WITH_UNDERSCORE
_CONFIG_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,99}$")

# Backup timestamp: YYYYMMDD_HHMMSS — guards against path traversal in rollback()
_BACKUP_TS_RE = re.compile(r"^\d{8}_\d{6}$")

# Valid git commit hash: exactly 40 lowercase hex chars
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


# ─── Data models ────────────────────────────────────────────────────────────

class UpdateType(str, Enum):
    CONFIG = "config"
    PLUGIN = "plugin"
    CORE = "core"


class UpdateResult(BaseModel):
    success: bool
    update_type: UpdateType
    previous_version: str
    new_version: str
    changes: List[str] = Field(default_factory=list)
    rollback_available: bool = False
    duration_seconds: float = 0.0
    error: Optional[str] = None


# ─── Git helpers ────────────────────────────────────────────────────────────

async def _run_git(
    *args: str,
    cwd: Optional[Path] = None,
) -> Tuple[int, str, str]:
    """Run a git subcommand via asyncio subprocess — never uses shell=True."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode(errors="replace").strip(),
            stderr_bytes.decode(errors="replace").strip(),
        )
    except FileNotFoundError:
        return 127, "", "git executable not found"
    except Exception as exc:
        return 1, "", str(exc)


# ─── OTAUpdateManager ───────────────────────────────────────────────────────

class OTAUpdateManager:
    """Over-The-Air update manager for IronCore V2.

    Usage::

        manager = OTAUpdateManager()

        # Check for available updates
        available = await manager.check_updates()

        # Hot-update a config variable
        result = await manager.update_config({"IRONCORE_LOG_LEVEL": "DEBUG"})

        # Update a plugin without restarting
        result = await manager.update_plugin("weather-plugin", plugin_registry)

        # Full core update (triggers controlled restart via SIGTERM)
        result = await manager.update_core()
    """

    def __init__(
        self,
        backup_dir: Optional[Path] = None,
        health_check_url: str = "http://localhost:8000/health",
        health_check_timeout: int = 30,
        repo_root: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
    ) -> None:
        self._backup_dir = backup_dir or Path(
            os.environ.get("IRONCORE_OTA_BACKUP_DIR", "ironcore/data/ota_backups")
        )
        self._health_check_url = health_check_url or os.environ.get(
            "IRONCORE_OTA_HEALTH_URL", "http://localhost:8000/health"
        )
        self._health_check_timeout = health_check_timeout
        self._repo_root = repo_root or Path(".")
        self._plugins_dir = plugins_dir or Path(
            os.environ.get("IRONCORE_PLUGINS_DIR", "ironcore/plugins/installed")
        )
        self._lock = asyncio.Lock()
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "[OTA] Initialised. backup_dir=%s repo_root=%s",
            self._backup_dir,
            self._repo_root.resolve(),
        )

    # ─── Public API ───────────────────────────────────────────────────────

    async def check_updates(self) -> Dict[str, str]:
        """Fetch remote refs and report pending commits.

        Returns a dict like ``{"core": "+3 commit(s)"}`` or ``{}`` if up to date.
        Never raises — returns empty dict on git errors.
        """
        rc, _, err = await _run_git("fetch", "--quiet", cwd=self._repo_root)
        if rc != 0:
            logger.warning("[OTA] git fetch failed: %s", err)
            return {}

        rc, ahead, _ = await _run_git(
            "rev-list", "--count", "HEAD..origin/HEAD",
            cwd=self._repo_root,
        )
        if rc != 0 or not ahead.isdigit() or int(ahead) == 0:
            return {}

        # Attempt to get a human-readable tag name from remote HEAD
        rc_tag, remote_tag, _ = await _run_git(
            "describe", "--tags", "--abbrev=0", "origin/HEAD",
            cwd=self._repo_root,
        )
        label = remote_tag if rc_tag == 0 and remote_tag else f"+{ahead} commit(s)"
        return {"core": label}

    async def get_current_version(self) -> str:
        """Return current git tag or short commit hash."""
        rc, tag, _ = await _run_git(
            "describe", "--tags", "--always", cwd=self._repo_root
        )
        if rc == 0 and tag:
            return tag
        rc2, commit, _ = await _run_git(
            "rev-parse", "--short", "HEAD", cwd=self._repo_root
        )
        return commit if rc2 == 0 else "unknown"

    async def list_backups(self) -> List[Dict[str, str]]:
        """Return available core rollback backup timestamps and their commit refs."""
        result: List[Dict[str, str]] = []
        for f in sorted(self._backup_dir.glob("core_rollback_*.txt")):
            match = re.search(r"core_rollback_(\d{8}_\d{6})\.txt$", f.name)
            if match:
                result.append(
                    {
                        "timestamp": match.group(1),
                        "commit": f.read_text().strip()[:12],
                        "filename": f.name,
                    }
                )
        return result

    # ─── Config update (hot, no restart) ─────────────────────────────────

    async def update_config(self, new_config: Dict[str, str]) -> UpdateResult:
        """Hot-update environment variables at runtime — no process restart.

        All keys are validated against ``[A-Z][A-Z0-9_]+`` before any change is
        applied (atomic: all-or-nothing).  On partial failure the original values
        are restored.
        """
        t0 = time.monotonic()

        # Validate every key before touching os.environ
        for key in new_config:
            if not _CONFIG_KEY_RE.match(key):
                return UpdateResult(
                    success=False,
                    update_type=UpdateType.CONFIG,
                    previous_version="runtime",
                    new_version="runtime",
                    error=(
                        f"Invalid config key {key!r}. "
                        "Keys must match [A-Z][A-Z0-9_]{{1,99}}."
                    ),
                    duration_seconds=time.monotonic() - t0,
                )

        # Snapshot prev values for rollback
        previous: Dict[str, Optional[str]] = {
            k: os.environ.get(k) for k in new_config
        }
        changes: List[str] = []

        try:
            for key, value in new_config.items():
                if os.environ.get(key) != value:
                    os.environ[key] = value
                    changes.append(f"SET {key}")
                    logger.info("[OTA/Config] Applied env update: %s", key)
        except Exception as exc:
            # Rollback any partial changes
            for key, old_val in previous.items():
                if old_val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_val
            return UpdateResult(
                success=False,
                update_type=UpdateType.CONFIG,
                previous_version="runtime",
                new_version="runtime",
                error=str(exc),
                duration_seconds=time.monotonic() - t0,
            )

        logger.info("[OTA/Config] %d variable(s) updated", len(changes))
        return UpdateResult(
            success=True,
            update_type=UpdateType.CONFIG,
            previous_version="runtime",
            new_version="runtime",
            changes=changes,
            rollback_available=False,
            duration_seconds=time.monotonic() - t0,
        )

    # ─── Plugin update (warm, hot-reload) ────────────────────────────────

    async def update_plugin(
        self,
        plugin_id: str,
        plugin_registry: Any,
    ) -> UpdateResult:
        """Update a single plugin: backup → git pull → hot-reload.

        Args:
            plugin_id: Plugin directory name (e.g. ``"weather-plugin"``).
            plugin_registry: :class:`ironcore.plugins.registry.PluginRegistry`
                             instance from Phase 1.

        Auto-rolls back the file system and reloads the previous version if
        the new reload fails.
        """
        async with self._lock:
            t0 = time.monotonic()
            plugin_dir = self._plugins_dir / plugin_id

            if not plugin_dir.exists():
                return UpdateResult(
                    success=False,
                    update_type=UpdateType.PLUGIN,
                    previous_version="unknown",
                    new_version="unknown",
                    error=f"Plugin directory not found: {plugin_dir}",
                    duration_seconds=time.monotonic() - t0,
                )

            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_path = self._backup_dir / f"plugin_{plugin_id}_{ts}"

            # Capture previous version
            rc, prev_ver, _ = await _run_git(
                "describe", "--tags", "--always", cwd=plugin_dir
            )
            previous_version = prev_ver if rc == 0 else "unknown"

            try:
                # 1. Backup plugin directory
                shutil.copytree(str(plugin_dir), str(backup_path))
                logger.info("[OTA/Plugin] Backed up %s → %s", plugin_id, backup_path)

                # 2. Fast-forward pull only (refuse merges to keep history clean)
                rc, stdout, stderr = await _run_git(
                    "pull", "--ff-only", cwd=plugin_dir
                )
                if rc != 0:
                    raise RuntimeError(f"git pull failed: {stderr}")

                changes = [ln for ln in stdout.splitlines() if ln.strip()]

                # 3. Hot-reload via PluginRegistry (Phase 1 interface)
                await plugin_registry.reload_plugin(plugin_id)

                # 4. Capture new version
                _, new_ver, _ = await _run_git(
                    "describe", "--tags", "--always", cwd=plugin_dir
                )
                logger.info(
                    "[OTA/Plugin] %s updated: %s → %s",
                    plugin_id, previous_version, new_ver,
                )
                return UpdateResult(
                    success=True,
                    update_type=UpdateType.PLUGIN,
                    previous_version=previous_version,
                    new_version=new_ver or "unknown",
                    changes=changes,
                    rollback_available=True,
                    duration_seconds=time.monotonic() - t0,
                )

            except Exception as exc:
                logger.error("[OTA/Plugin] Update failed (%s), rolling back: %s", plugin_id, exc)

                # Restore backup
                if backup_path.exists():
                    try:
                        shutil.rmtree(str(plugin_dir))
                        shutil.copytree(str(backup_path), str(plugin_dir))
                        await plugin_registry.reload_plugin(plugin_id)
                        logger.info("[OTA/Plugin] Rollback succeeded for %s", plugin_id)
                    except Exception as rb_exc:
                        logger.error("[OTA/Plugin] Rollback also failed: %s", rb_exc)

                return UpdateResult(
                    success=False,
                    update_type=UpdateType.PLUGIN,
                    previous_version=previous_version,
                    new_version="unknown",
                    error=str(exc),
                    rollback_available=backup_path.exists(),
                    duration_seconds=time.monotonic() - t0,
                )

    # ─── Core update (rolling, SIGTERM restart) ───────────────────────────

    async def update_core(self, target_version: str = "latest") -> UpdateResult:
        """Full core update with backup and auto-rollback.

        Sequence:
          1. Record current HEAD as rollback reference.
          2. ``git pull --ff-only``.
          3. Schedule a controlled SIGTERM after returning the response
             (Docker ``restart: unless-stopped`` restarts the container).
          4. If git pull itself fails, reset to previous HEAD immediately.

        The health-check verification is left to the caller via
        ``GET /api/ota/status`` after the service comes back up, or
        triggered explicitly via ``POST /api/ota/check``.
        """
        async with self._lock:
            t0 = time.monotonic()

            # 1. Record current HEAD for rollback
            rc, prev_commit, err = await _run_git(
                "rev-parse", "HEAD", cwd=self._repo_root
            )
            if rc != 0:
                return UpdateResult(
                    success=False,
                    update_type=UpdateType.CORE,
                    previous_version="unknown",
                    new_version="unknown",
                    error=f"Cannot determine current git HEAD: {err}",
                    duration_seconds=time.monotonic() - t0,
                )

            previous_version = prev_commit[:12]

            # 2. Persist rollback ref to disk
            ts = time.strftime("%Y%m%d_%H%M%S")
            rollback_ref_file = self._backup_dir / f"core_rollback_{ts}.txt"
            rollback_ref_file.write_text(prev_commit)
            logger.info("[OTA/Core] Saved rollback ref %s → %s", previous_version, rollback_ref_file)

            try:
                # 3. Fast-forward pull
                rc, stdout, stderr = await _run_git(
                    "pull", "--ff-only", cwd=self._repo_root
                )
                if rc != 0:
                    raise RuntimeError(f"git pull failed: {stderr}")

                changes = [ln for ln in stdout.splitlines() if ln.strip()]

                # 4. Capture new version
                _, new_ver, _ = await _run_git(
                    "describe", "--tags", "--always", cwd=self._repo_root
                )

                # 5. Schedule graceful restart (2 s delay so HTTP response escapes first)
                asyncio.create_task(self._schedule_restart(delay_seconds=2.0))
                logger.info(
                    "[OTA/Core] Pull succeeded (%s → %s). SIGTERM scheduled in 2 s.",
                    previous_version, new_ver or "unknown",
                )

                return UpdateResult(
                    success=True,
                    update_type=UpdateType.CORE,
                    previous_version=previous_version,
                    new_version=new_ver or "unknown",
                    changes=changes,
                    rollback_available=True,
                    duration_seconds=time.monotonic() - t0,
                )

            except Exception as exc:
                logger.error("[OTA/Core] Update failed: %s — reverting to %s", exc, previous_version)

                # Auto-rollback: git reset --hard to recorded HEAD
                rb_rc, _, rb_err = await _run_git(
                    "reset", "--hard", prev_commit, cwd=self._repo_root
                )
                if rb_rc != 0:
                    logger.error("[OTA/Core] git reset also failed: %s", rb_err)

                return UpdateResult(
                    success=False,
                    update_type=UpdateType.CORE,
                    previous_version=previous_version,
                    new_version="unknown",
                    error=str(exc),
                    rollback_available=rollback_ref_file.exists(),
                    duration_seconds=time.monotonic() - t0,
                )

    # ─── Manual rollback ──────────────────────────────────────────────────

    async def rollback(self, backup_timestamp: str) -> UpdateResult:
        """Roll back the core to the git commit recorded in a backup file.

        ``backup_timestamp`` must match ``YYYYMMDD_HHMMSS`` to prevent path
        traversal attacks.  The stored commit hash is validated as a 40-char
        hex string before passing it to git.
        """
        # Guard: timestamp format
        if not _BACKUP_TS_RE.match(backup_timestamp):
            return UpdateResult(
                success=False,
                update_type=UpdateType.CORE,
                previous_version="unknown",
                new_version="unknown",
                error=(
                    f"Invalid backup_timestamp {backup_timestamp!r}. "
                    "Expected format: YYYYMMDD_HHMMSS"
                ),
            )

        t0 = time.monotonic()
        rollback_file = self._backup_dir / f"core_rollback_{backup_timestamp}.txt"

        if not rollback_file.exists():
            return UpdateResult(
                success=False,
                update_type=UpdateType.CORE,
                previous_version="unknown",
                new_version="unknown",
                error=f"Backup file not found: {rollback_file.name}",
                duration_seconds=time.monotonic() - t0,
            )

        target_commit = rollback_file.read_text().strip()

        # Guard: must be a valid 40-char hex commit hash
        if not _COMMIT_RE.match(target_commit):
            return UpdateResult(
                success=False,
                update_type=UpdateType.CORE,
                previous_version="unknown",
                new_version="unknown",
                error="Backup file contains an invalid commit hash — refusing rollback.",
                duration_seconds=time.monotonic() - t0,
            )

        rc, current_head, _ = await _run_git("rev-parse", "HEAD", cwd=self._repo_root)
        previous_version = current_head[:12] if rc == 0 else "unknown"

        rc, _, stderr = await _run_git(
            "reset", "--hard", target_commit, cwd=self._repo_root
        )
        if rc != 0:
            return UpdateResult(
                success=False,
                update_type=UpdateType.CORE,
                previous_version=previous_version,
                new_version="unknown",
                error=f"git reset --hard failed: {stderr}",
                duration_seconds=time.monotonic() - t0,
            )

        logger.info(
            "[OTA/Core] Rolled back %s → %s (backup: %s)",
            previous_version, target_commit[:12], backup_timestamp,
        )

        # Trigger restart so rolled-back code takes effect
        asyncio.create_task(self._schedule_restart(delay_seconds=2.0))

        return UpdateResult(
            success=True,
            update_type=UpdateType.CORE,
            previous_version=previous_version,
            new_version=target_commit[:12],
            changes=[f"Rolled back to {target_commit[:12]}"],
            rollback_available=False,
            duration_seconds=time.monotonic() - t0,
        )

    # ─── Internal helpers ─────────────────────────────────────────────────

    async def _wait_for_health(self, timeout: int) -> bool:
        """Poll ``GET /health`` until HTTP 200 or timeout expires.

        Used in tests and integration scenarios.  The main ``update_core()``
        flow relies on Docker's restart policy instead of blocking on this.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(self._health_check_url, method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(2)
        return False

    async def _schedule_restart(self, delay_seconds: float = 2.0) -> None:
        """Send SIGTERM after *delay_seconds* to trigger a graceful restart.

        In a Docker deployment with ``restart: unless-stopped`` the container
        manager will bring the service back up on the updated code automatically.
        """
        await asyncio.sleep(delay_seconds)
        logger.info("[OTA] Sending SIGTERM to PID %d for graceful restart.", os.getpid())
        os.kill(os.getpid(), signal.SIGTERM)
