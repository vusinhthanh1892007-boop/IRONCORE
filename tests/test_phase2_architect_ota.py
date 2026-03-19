"""
IronCore V2 — Phase 2 OTA Update Manager Tests
================================================
Phase 2 — The Architect (Gemini 3.1)

Test coverage:
  - update_config: happy path, invalid key rejected, partial rollback
  - update_plugin: success flow, git pull fail → rollback
  - update_core: success flow, git pull fail → auto git-reset
  - rollback: valid timestamp, invalid timestamp format, missing file, bad hash
  - check_updates: no updates, updates available
  - _schedule_restart: mocked — does NOT send actual SIGTERM during tests

Run:
    pytest tests/test_phase2_architect_ota.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ironcore.ota.manager import OTAUpdateManager, UpdateType, _COMMIT_RE


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_backup_dir(tmp_path: Path) -> Path:
    bd = tmp_path / "ota_backups"
    bd.mkdir()
    return bd


@pytest.fixture()
def manager(tmp_backup_dir: Path, tmp_path: Path) -> OTAUpdateManager:
    return OTAUpdateManager(
        backup_dir=tmp_backup_dir,
        health_check_url="http://localhost:9999/health",
        health_check_timeout=5,
        repo_root=tmp_path,
        plugins_dir=tmp_path / "plugins",
    )


# ─── update_config ───────────────────────────────────────────────────────────

class TestConfigUpdate:
    @pytest.mark.asyncio
    async def test_config_update_sets_env_var(self, manager: OTAUpdateManager) -> None:
        """Config update must write new value to os.environ."""
        key = "IRONCORE_OTA_TEST_HAPPY"
        os.environ.pop(key, None)

        result = await manager.update_config({key: "hello_world"})

        assert result.success is True
        assert result.update_type == UpdateType.CONFIG
        assert os.environ.get(key) == "hello_world"
        assert any("IRONCORE_OTA_TEST_HAPPY" in c for c in result.changes)
        # Cleanup
        os.environ.pop(key, None)

    @pytest.mark.asyncio
    async def test_config_update_invalid_key_rejected(self, manager: OTAUpdateManager) -> None:
        """Key with special characters must be rejected before any env change."""
        bad_key = "bad-key; rm -rf /"
        result = await manager.update_config({bad_key: "value"})

        assert result.success is False
        assert "Invalid config key" in (result.error or "")
        assert os.environ.get(bad_key) is None

    @pytest.mark.asyncio
    async def test_config_update_lowercase_key_rejected(self, manager: OTAUpdateManager) -> None:
        """Lowercase keys must fail validation."""
        result = await manager.update_config({"ironcore_lower": "val"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_config_update_no_change_skipped(self, manager: OTAUpdateManager) -> None:
        """Key already set to the same value should produce zero changes."""
        key = "IRONCORE_OTA_TEST_NOCHANGE"
        os.environ[key] = "same"

        result = await manager.update_config({key: "same"})

        assert result.success is True
        assert len(result.changes) == 0
        os.environ.pop(key, None)

    @pytest.mark.asyncio
    async def test_config_update_mixed_valid_invalid_rejected_atomically(
        self, manager: OTAUpdateManager
    ) -> None:
        """A mix of valid + invalid keys must reject ALL without touching env."""
        good_key = "IRONCORE_OTA_TEST_ATOMIC"
        bad_key = "bad key"
        os.environ.pop(good_key, None)

        result = await manager.update_config({good_key: "should_not_set", bad_key: "x"})

        assert result.success is False
        # good key must NOT have been applied
        assert os.environ.get(good_key) is None
        os.environ.pop(good_key, None)


# ─── update_plugin ───────────────────────────────────────────────────────────

class TestPluginUpdate:
    @pytest.mark.asyncio
    async def test_plugin_update_success(self, manager: OTAUpdateManager, tmp_path: Path) -> None:
        """Successful plugin update should call reload_plugin and return success."""
        plugin_id = "test-plugin"
        plugin_dir = tmp_path / "plugins" / plugin_id
        plugin_dir.mkdir(parents=True)

        mock_registry = AsyncMock()

        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["pull", "--ff-only"] == cmd:
                return 0, "Already up to date.\nFast-forward", ""
            if ["describe", "--tags", "--always"] == cmd:
                return 0, "v1.2.0", ""
            return 0, "", ""

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.update_plugin(plugin_id, mock_registry)

        assert result.success is True
        assert result.update_type == UpdateType.PLUGIN
        mock_registry.reload_plugin.assert_called_once_with(plugin_id)

    @pytest.mark.asyncio
    async def test_plugin_update_git_pull_fail_triggers_rollback(
        self, manager: OTAUpdateManager, tmp_path: Path
    ) -> None:
        """git pull failure must restore the backup and still call reload_plugin."""
        plugin_id = "fail-plugin"
        plugin_dir = tmp_path / "plugins" / plugin_id
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "main.py").write_text("# original")

        mock_registry = AsyncMock()

        call_count = {"n": 0}

        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["pull", "--ff-only"] == cmd:
                return 1, "", "remote: Repository not found."
            return 0, "v0.9.0", ""

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.update_plugin(plugin_id, mock_registry)

        assert result.success is False
        assert "git pull failed" in (result.error or "")
        # Rollback should have re-called reload_plugin
        mock_registry.reload_plugin.assert_called_with(plugin_id)

    @pytest.mark.asyncio
    async def test_plugin_update_missing_directory(self, manager: OTAUpdateManager) -> None:
        """Non-existent plugin directory must return failure without crashing."""
        result = await manager.update_plugin("ghost-plugin", AsyncMock())
        assert result.success is False
        assert "not found" in (result.error or "").lower()


# ─── update_core ─────────────────────────────────────────────────────────────

class TestCoreUpdate:
    @pytest.mark.asyncio
    async def test_core_update_success(
        self, manager: OTAUpdateManager, tmp_backup_dir: Path
    ) -> None:
        """Successful git pull must create a rollback file and schedule restart."""
        fake_commit = "a" * 40

        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["rev-parse", "HEAD"] == cmd:
                return 0, fake_commit, ""
            if ["pull", "--ff-only"] == cmd:
                return 0, "Updating abc..def\nFast-forward\n main.py | 2 ++", ""
            if ["describe", "--tags", "--always"] == cmd:
                return 0, "v2.1.0", ""
            return 0, "", ""

        restart_scheduled = []

        async def fake_restart(delay_seconds: float = 2.0) -> None:
            restart_scheduled.append(delay_seconds)

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            with patch.object(manager, "_schedule_restart", side_effect=fake_restart):
                result = await manager.update_core()

        assert result.success is True
        assert result.update_type == UpdateType.CORE
        assert result.new_version == "v2.1.0"
        assert result.rollback_available is True

        # Rollback ref file must exist
        backups = list(tmp_backup_dir.glob("core_rollback_*.txt"))
        assert len(backups) == 1
        assert backups[0].read_text().strip() == fake_commit

    @pytest.mark.asyncio
    async def test_core_update_git_pull_fail_auto_reverts(
        self, manager: OTAUpdateManager
    ) -> None:
        """git pull failure must trigger ``git reset --hard`` to previous HEAD."""
        fake_commit = "b" * 40
        reset_calls: list = []

        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["rev-parse", "HEAD"] == cmd:
                return 0, fake_commit, ""
            if ["pull", "--ff-only"] == cmd:
                return 1, "", "CONFLICT (content): Merge conflict"
            if cmd[:2] == ["reset", "--hard"]:
                reset_calls.append(cmd[2])
                return 0, "", ""
            return 0, "", ""

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.update_core()

        assert result.success is False
        assert "git pull failed" in (result.error or "")
        # Rollback must have reset to the original commit
        assert fake_commit in reset_calls

    @pytest.mark.asyncio
    async def test_core_update_no_git_returns_error(self, manager: OTAUpdateManager) -> None:
        """If we cannot determine HEAD (git unavailable), return failure cleanly."""
        async def fake_git(*args, cwd=None):
            return 127, "", "git executable not found"

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.update_core()

        assert result.success is False
        assert result.previous_version == "unknown"


# ─── rollback ────────────────────────────────────────────────────────────────

class TestRollback:
    @pytest.mark.asyncio
    async def test_rollback_valid_timestamp_succeeds(
        self, manager: OTAUpdateManager, tmp_backup_dir: Path
    ) -> None:
        """Valid backup timestamp + commit hash must execute git reset."""
        ts = "20260311_143000"
        commit = "c" * 40
        (tmp_backup_dir / f"core_rollback_{ts}.txt").write_text(commit)

        reset_calls: list = []

        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["rev-parse", "HEAD"] == cmd:
                return 0, "d" * 40, ""
            if cmd[:2] == ["reset", "--hard"]:
                reset_calls.append(cmd[2])
                return 0, "", ""
            return 0, "", ""

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            with patch.object(manager, "_schedule_restart", new=AsyncMock()):
                result = await manager.rollback(ts)

        assert result.success is True
        assert commit in reset_calls

    @pytest.mark.asyncio
    async def test_rollback_invalid_timestamp_format_rejected(
        self, manager: OTAUpdateManager
    ) -> None:
        """Malformed timestamps (e.g. path traversal) must be rejected immediately."""
        for bad_ts in ["../../../etc/passwd", "2026-03-11", "latest", '"; rm -rf /']:
            result = await manager.rollback(bad_ts)
            assert result.success is False
            assert "Invalid backup_timestamp" in (result.error or "")

    @pytest.mark.asyncio
    async def test_rollback_missing_backup_file(self, manager: OTAUpdateManager) -> None:
        """Requesting a non-existent backup timestamp must return failure."""
        result = await manager.rollback("20260101_000000")
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_rollback_invalid_commit_hash_rejected(
        self, manager: OTAUpdateManager, tmp_backup_dir: Path
    ) -> None:
        """A backup file containing a non-hex string must be rejected before git call."""
        ts = "20260311_150000"
        (tmp_backup_dir / f"core_rollback_{ts}.txt").write_text(
            "not-a-real-commit-hash; rm -rf /"
        )
        result = await manager.rollback(ts)
        assert result.success is False
        assert "invalid commit hash" in (result.error or "").lower()


# ─── check_updates ───────────────────────────────────────────────────────────

class TestCheckUpdates:
    @pytest.mark.asyncio
    async def test_no_updates_returns_empty(self, manager: OTAUpdateManager) -> None:
        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["fetch", "--quiet"] == cmd:
                return 0, "", ""
            if ["rev-list", "--count", "HEAD..origin/HEAD"] == cmd:
                return 0, "0", ""
            return 0, "", ""

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.check_updates()

        assert result == {}

    @pytest.mark.asyncio
    async def test_updates_available_returns_version(self, manager: OTAUpdateManager) -> None:
        async def fake_git(*args, cwd=None):
            cmd = list(args)
            if ["fetch", "--quiet"] == cmd:
                return 0, "", ""
            if ["rev-list", "--count", "HEAD..origin/HEAD"] == cmd:
                return 0, "5", ""
            if ["describe", "--tags", "--abbrev=0", "origin/HEAD"] == cmd:
                return 0, "v2.3.0", ""
            return 0, "", ""

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.check_updates()

        assert "core" in result
        assert result["core"] == "v2.3.0"

    @pytest.mark.asyncio
    async def test_git_fetch_fail_returns_empty(self, manager: OTAUpdateManager) -> None:
        async def fake_git(*args, cwd=None):
            return 1, "", "network error"

        with patch("ironcore.ota.manager._run_git", side_effect=fake_git):
            result = await manager.check_updates()

        assert result == {}


# ─── Commit hash regex sanity check ──────────────────────────────────────────

class TestCommitHashRegex:
    def test_valid_commit_accepted(self) -> None:
        assert _COMMIT_RE.match("a" * 40)
        assert _COMMIT_RE.match("0123456789abcdef" * 2 + "01234567")

    def test_invalid_commits_rejected(self) -> None:
        assert not _COMMIT_RE.match("abc123")                  # too short
        assert not _COMMIT_RE.match("A" * 40)                  # uppercase
        assert not _COMMIT_RE.match("g" * 40)                  # invalid hex char
        assert not _COMMIT_RE.match("a" * 39 + ";rm -rf /")   # injection attempt
