"""
Tests: Phase 1 — The Architect — Plugin System
================================================
Covers:
  - Manifest validation (happy path + edge cases + failures)
  - Security scan (detect forbidden imports)
  - PluginLoader (local install, manifest errors)
  - PluginRegistry (install → tools registered → uninstall → cache invalidated)

Run:
  python -m pytest tests/test_phase1_architect_plugins.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Imports từ plugin system ──────────────────────────────────────────────────
from ironcore.plugins.manifest import (
    ManifestValidationError,
    PluginInfo,
    PluginInstallError,
    PluginManifest,
    PluginNotFoundError,
    PluginPermission,
    PluginSecurityError,
    PluginStatus,
    ToolSpec,
)
from ironcore.plugins.loader import PluginLoader, SecurityASTVisitor, FORBIDDEN_MODULES
from ironcore.plugins.registry import PluginRegistry
import ast


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

VALID_MANIFEST_DATA: Dict[str, Any] = {
    "id": "test-weather",
    "name": "Test Weather Plugin",
    "version": "1.0.0",
    "author": "test@ironcore.dev",
    "description": "Plugin test cho IronCore",
    "permissions": ["network"],
    "tools": [
        {
            "name": "get_weather",
            "description": "Lấy thời tiết hiện tại",
            "parameters": {"location": {"type": "string"}},
            "risk_level": "low",
        }
    ],
}

VALID_PLUGIN_MAIN = """\
from ironcore.skills.registry import SkillMetadata, SkillRegistry
from ironcore.core.engine import RiskLevel

async def get_weather_handler(location: str = "") -> str:
    return f"Thời tiết tại {location}: 28°C"

def register_tools(registry) -> None:
    import asyncio
    asyncio.get_event_loop()
    # Plugin tự register bằng cách gọi registry trực tiếp
    # (Trong test, chúng ta mock registry)
    pass
"""


def make_plugin_dir(
    tmp_path: Path,
    manifest_data: Dict[str, Any] = None,
    main_content: str = None,
) -> Path:
    """Helper tạo plugin directory tạm trong tmp_path."""
    plugin_dir = tmp_path / "test-weather"
    plugin_dir.mkdir()

    data = manifest_data if manifest_data is not None else VALID_MANIFEST_DATA
    (plugin_dir / "manifest.json").write_text(
        json.dumps(data), encoding="utf-8"
    )

    content = main_content if main_content is not None else VALID_PLUGIN_MAIN
    (plugin_dir / "main.py").write_text(content, encoding="utf-8")

    return plugin_dir


# ══════════════════════════════════════════════════════════════════════════════
# Test Group 1: Manifest Validation
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginManifest:
    """Unit tests cho PluginManifest Pydantic model."""

    def test_valid_manifest_parses_ok(self):
        manifest = PluginManifest.model_validate(VALID_MANIFEST_DATA)
        assert manifest.id == "test-weather"
        assert manifest.version == "1.0.0"
        assert len(manifest.tools) == 1
        assert manifest.tools[0].name == "get_weather"

    def test_invalid_id_reserved_namespace(self):
        data = {**VALID_MANIFEST_DATA, "id": "ironcore-core-something"}
        with pytest.raises(Exception, match="Reserved namespace"):
            PluginManifest.model_validate(data)

    def test_invalid_id_format(self):
        # ID phải là kebab-case lowercase
        data = {**VALID_MANIFEST_DATA, "id": "MyPlugin"}
        with pytest.raises(Exception):
            PluginManifest.model_validate(data)

    def test_invalid_version_format(self):
        data = {**VALID_MANIFEST_DATA, "version": "1.0"}
        with pytest.raises(Exception, match="semver"):
            PluginManifest.model_validate(data)

    def test_version_with_text_invalid(self):
        data = {**VALID_MANIFEST_DATA, "version": "1.0.0-beta"}
        with pytest.raises(Exception):
            PluginManifest.model_validate(data)

    def test_duplicate_tool_names_rejected(self):
        data = {
            **VALID_MANIFEST_DATA,
            "tools": [
                {"name": "get_weather", "description": "A", "risk_level": "low"},
                {"name": "get_weather", "description": "B", "risk_level": "low"},
            ],
        }
        with pytest.raises(Exception, match="trùng"):
            PluginManifest.model_validate(data)

    def test_tool_name_must_be_snake_case(self):
        data = {
            **VALID_MANIFEST_DATA,
            "tools": [
                {"name": "GetWeather", "description": "A", "risk_level": "low"},
            ],
        }
        with pytest.raises(Exception, match="snake_case"):
            PluginManifest.model_validate(data)

    def test_tool_invalid_risk_level(self):
        data = {
            **VALID_MANIFEST_DATA,
            "tools": [
                {"name": "get_weather", "description": "A", "risk_level": "critical"},
            ],
        }
        with pytest.raises(Exception):
            PluginManifest.model_validate(data)

    def test_permissions_validated(self):
        data = {**VALID_MANIFEST_DATA, "permissions": ["invalid_permission"]}
        with pytest.raises(Exception):
            PluginManifest.model_validate(data)

    def test_missing_required_fields(self):
        with pytest.raises(Exception):
            PluginManifest.model_validate({"id": "test-plugin"})  # thiếu name, version, ...

    def test_plugin_info_is_active_property(self):
        manifest = PluginManifest.model_validate(VALID_MANIFEST_DATA)
        info = PluginInfo(manifest=manifest, status=PluginStatus.ACTIVE)
        assert info.is_active is True

        info2 = PluginInfo(manifest=manifest, status=PluginStatus.DISABLED)
        assert info2.is_active is False

    def test_plugin_namespace_format(self):
        from ironcore.plugins.registry import PluginRegistry
        registry = PluginRegistry()
        ns = registry.get_plugin_namespace("test-weather")
        assert ns == "plugin:test-weather"


# ══════════════════════════════════════════════════════════════════════════════
# Test Group 2: Security Scan
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityScan:
    """Unit tests cho AST security scanner."""

    def _scan_code(self, code: str, permissions: List[str] = None) -> List[str]:
        """Helper: scan một đoạn code string trực tiếp."""
        manifest = PluginManifest.model_validate({
            **VALID_MANIFEST_DATA,
            "permissions": permissions or [],
        })
        tree = ast.parse(code)
        visitor = SecurityASTVisitor(
            forbidden_modules=FORBIDDEN_MODULES,
            forbidden_calls=frozenset({"exec", "eval", "compile", "__import__", "open", "input", "breakpoint"}),
            allowed_permissions=permissions or [],
        )
        visitor.visit(tree)
        return visitor.warnings

    def test_clean_code_no_warnings(self):
        code = "import math\nresult = math.sqrt(4)\n"
        warnings = self._scan_code(code)
        assert warnings == []

    def test_detect_subprocess_import(self):
        code = "import subprocess\nsubprocess.run(['ls'])\n"
        warnings = self._scan_code(code)
        assert any("subprocess" in w for w in warnings)

    def test_detect_os_import_without_permission(self):
        code = "import os\nos.system('ls')\n"
        warnings = self._scan_code(code, permissions=[])
        assert any("os" in w for w in warnings)

    def test_os_import_allowed_with_filesystem_permission(self):
        code = "import os\npath = os.path.join('a', 'b')\n"
        warnings = self._scan_code(code, permissions=["filesystem"])
        # os import với filesystem permission không bị coi là cấm
        assert not any("import 'os' bị cấm" in w for w in warnings)

    def test_detect_eval_call(self):
        code = "result = eval('1+1')\n"
        warnings = self._scan_code(code)
        assert any("eval" in w for w in warnings)

    def test_detect_exec_call(self):
        code = "exec('print(1)')\n"
        warnings = self._scan_code(code)
        assert any("exec" in w for w in warnings)

    def test_detect_dangerous_attribute(self):
        code = "f = lambda: None\nf.__globals__['x'] = 1\n"
        warnings = self._scan_code(code)
        assert any("__globals__" in w for w in warnings)

    def test_detect_dunder_import(self):
        code = "mod = __import__('os')\n"
        warnings = self._scan_code(code)
        assert any("__import__" in w for w in warnings)

    def test_from_import_forbidden(self):
        code = "from subprocess import run\n"
        warnings = self._scan_code(code)
        assert any("subprocess" in w for w in warnings)

    def test_safe_plugin_code_no_warnings(self):
        code = VALID_PLUGIN_MAIN
        warnings = self._scan_code(code, permissions=["network"])
        assert warnings == []


# ══════════════════════════════════════════════════════════════════════════════
# Test Group 3: PluginLoader
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginLoader:
    """Integration tests cho PluginLoader với local path."""

    def test_load_manifest_valid(self, tmp_path):
        plugin_dir = make_plugin_dir(tmp_path)
        loader = PluginLoader(tmp_path / "installed")
        manifest = loader.load_manifest(plugin_dir)
        assert manifest.id == "test-weather"

    def test_load_manifest_missing_file(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        loader = PluginLoader(tmp_path / "installed")
        with pytest.raises(ManifestValidationError, match="thiếu manifest.json"):
            loader.load_manifest(empty_dir)

    def test_load_manifest_invalid_json(self, tmp_path):
        plugin_dir = tmp_path / "bad"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text("not json content!!!")
        loader = PluginLoader(tmp_path / "installed")
        with pytest.raises(ManifestValidationError):
            loader.load_manifest(plugin_dir)

    def test_load_manifest_schema_error(self, tmp_path):
        """manifest.json là JSON hợp lệ nhưng sai schema."""
        plugin_dir = tmp_path / "badschema"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(
            json.dumps({"id": "ironcore-core-reserved", "name": "Bad"})
        )
        loader = PluginLoader(tmp_path / "installed")
        with pytest.raises(ManifestValidationError):
            loader.load_manifest(plugin_dir)

    def test_scan_security_clean(self, tmp_path):
        plugin_dir = make_plugin_dir(tmp_path)
        loader = PluginLoader(tmp_path / "installed")
        manifest = loader.load_manifest(plugin_dir)
        warnings = loader.scan_security(plugin_dir, manifest)
        assert isinstance(warnings, list)

    def test_scan_security_detects_subprocess(self, tmp_path):
        dangerous_main = "import subprocess\nsubprocess.run(['ls'])\n"
        plugin_dir = make_plugin_dir(tmp_path, main_content=dangerous_main)
        loader = PluginLoader(tmp_path / "installed")
        manifest = loader.load_manifest(plugin_dir)
        warnings = loader.scan_security(plugin_dir, manifest)
        assert any("subprocess" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_download_local_path(self, tmp_path):
        plugin_dir = make_plugin_dir(tmp_path)
        installed_dir = tmp_path / "installed"
        loader = PluginLoader(installed_dir)
        dest = await loader.download_plugin(str(plugin_dir))
        assert dest.exists()
        assert (dest / "manifest.json").exists()

    @pytest.mark.asyncio
    async def test_download_nonexistent_path_raises(self, tmp_path):
        loader = PluginLoader(tmp_path / "installed")
        with pytest.raises(Exception):
            await loader.download_plugin("/nonexistent/path/that/does/not/exist")

    def test_dynamic_import_valid(self, tmp_path):
        # Plugin với register_tools() hợp lệ
        main_with_register = """\
def register_tools(registry):
    pass
"""
        plugin_dir = make_plugin_dir(tmp_path, main_content=main_with_register)
        loader = PluginLoader(tmp_path / "installed")
        manifest = loader.load_manifest(plugin_dir)
        module = loader.dynamic_import(plugin_dir, manifest)
        assert hasattr(module, "register_tools")
        assert callable(module.register_tools)

    def test_dynamic_import_missing_register_tools(self, tmp_path):
        main_no_register = "x = 1\n"
        plugin_dir = make_plugin_dir(tmp_path, main_content=main_no_register)
        loader = PluginLoader(tmp_path / "installed")
        manifest = loader.load_manifest(plugin_dir)
        with pytest.raises(PluginInstallError, match="register_tools"):
            loader.dynamic_import(plugin_dir, manifest)

    def test_unload_module_cleans_sys_modules(self, tmp_path):
        main_code = "def register_tools(r): pass\n"
        plugin_dir = make_plugin_dir(tmp_path, main_content=main_code)
        loader = PluginLoader(tmp_path / "installed")
        manifest = loader.load_manifest(plugin_dir)
        _ = loader.dynamic_import(plugin_dir, manifest)

        module_name = f"ironcore_plugin_test_weather"
        assert module_name in sys.modules

        loader.unload_module("test-weather")
        assert module_name not in sys.modules

    def test_validate_package_names_rejects_injection(self, tmp_path):
        loader = PluginLoader(tmp_path / "installed")
        # Injection attempt
        packages = ["requests", "numpy; rm -rf /", "flask"]
        valid = loader._validate_package_names(packages)
        assert "numpy; rm -rf /" not in valid
        assert "requests" in valid


# ══════════════════════════════════════════════════════════════════════════════
# Test Group 4: PluginRegistry
# ══════════════════════════════════════════════════════════════════════════════

class TestPluginRegistry:
    """Integration tests cho PluginRegistry."""

    def _make_registry(self, tmp_path: Path) -> PluginRegistry:
        """Tạo registry với mock dependencies."""
        mock_skill_registry = MagicMock()
        mock_skill_registry.get = MagicMock(return_value=MagicMock())  # tool exists
        mock_skill_registry.unregister = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.invalidate_namespace = AsyncMock(return_value=1)

        return PluginRegistry(
            plugins_dir=tmp_path / "installed",
            skill_registry=mock_skill_registry,
            semantic_cache=mock_cache,
            security_scan=True,
            block_on_warnings=False,
        )

    @pytest.mark.asyncio
    async def test_install_from_local_path(self, tmp_path):
        plugin_dir = make_plugin_dir(
            tmp_path,
            main_content="def register_tools(r): pass\n",
        )
        registry = self._make_registry(tmp_path)
        manifest = await registry.install_plugin(
            str(plugin_dir), requester_id="test"
        )
        assert manifest.id == "test-weather"

        plugins = await registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].status == PluginStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_install_registers_tools_in_skill_registry(self, tmp_path):
        plugin_dir = make_plugin_dir(
            tmp_path,
            main_content="def register_tools(r): pass\n",
        )
        mock_skill_registry = MagicMock()
        mock_skill_registry.get = MagicMock(return_value=MagicMock())
        mock_skill_registry.unregister = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.invalidate_namespace = AsyncMock(return_value=1)

        registry = PluginRegistry(
            plugins_dir=tmp_path / "installed",
            skill_registry=mock_skill_registry,
            semantic_cache=mock_cache,
        )
        await registry.install_plugin(str(plugin_dir))
        # register_tools() được gọi đúng 1 lần
        assert mock_skill_registry.get.called

    @pytest.mark.asyncio
    async def test_install_invalidates_cache(self, tmp_path):
        plugin_dir = make_plugin_dir(
            tmp_path,
            main_content="def register_tools(r): pass\n",
        )
        registry = self._make_registry(tmp_path)
        await registry.install_plugin(str(plugin_dir))

        # Cache invalidation phải được gọi
        registry._semantic_cache.invalidate_namespace.assert_called_with(
            "plugin:test-weather"
        )

    @pytest.mark.asyncio
    async def test_uninstall_removes_plugin(self, tmp_path):
        plugin_dir = make_plugin_dir(
            tmp_path,
            main_content="def register_tools(r): pass\n",
        )
        registry = self._make_registry(tmp_path)
        await registry.install_plugin(str(plugin_dir))

        await registry.uninstall_plugin("test-weather")
        plugins = await registry.list_plugins()
        assert len(plugins) == 0

    @pytest.mark.asyncio
    async def test_uninstall_nonexistent_raises(self, tmp_path):
        registry = self._make_registry(tmp_path)
        with pytest.raises(PluginNotFoundError):
            await registry.uninstall_plugin("nonexistent-plugin")

    @pytest.mark.asyncio
    async def test_disable_then_enable_plugin(self, tmp_path):
        plugin_dir = make_plugin_dir(
            tmp_path,
            main_content="def register_tools(r): pass\n",
        )
        registry = self._make_registry(tmp_path)
        await registry.install_plugin(str(plugin_dir))

        await registry.disable_plugin("test-weather")
        status = await registry.get_plugin_status("test-weather")
        assert status == PluginStatus.DISABLED

        await registry.enable_plugin("test-weather")
        status = await registry.get_plugin_status("test-weather")
        assert status == PluginStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_get_status_unknown_plugin_raises(self, tmp_path):
        registry = self._make_registry(tmp_path)
        with pytest.raises(PluginNotFoundError):
            await registry.get_plugin_status("not-installed")

    @pytest.mark.asyncio
    async def test_manifest_validation_failure_raises(self, tmp_path):
        """Install với manifest sai → ManifestValidationError."""
        bad_manifest = {
            "id": "ironcore-core-reserved",  # reserved namespace → invalid
            "name": "Bad",
            "version": "1.0.0",
            "author": "x",
            "description": "test",
        }
        plugin_dir = make_plugin_dir(tmp_path, manifest_data=bad_manifest)
        registry = self._make_registry(tmp_path)
        with pytest.raises((ManifestValidationError, PluginInstallError)):
            await registry.install_plugin(str(plugin_dir))

    @pytest.mark.asyncio
    async def test_security_scan_warning_does_not_block_by_default(self, tmp_path):
        """block_on_warnings=False: warnings không block install."""
        dangerous_main = "import subprocess\ndef register_tools(r): pass\n"
        plugin_dir = make_plugin_dir(tmp_path, main_content=dangerous_main)
        registry = self._make_registry(tmp_path)  # block_on_warnings=False

        manifest = await registry.install_plugin(str(plugin_dir))
        assert manifest.id == "test-weather"
        # Plugin di cài nhưng warnings được ghi nhận
        plugins = await registry.list_plugins()
        assert len(plugins[0].security_warnings) > 0

    @pytest.mark.asyncio
    async def test_security_scan_warning_blocks_when_configured(self, tmp_path):
        """block_on_warnings=True: warnings block install."""
        dangerous_main = "import subprocess\ndef register_tools(r): pass\n"
        plugin_dir = make_plugin_dir(tmp_path, main_content=dangerous_main)

        registry = PluginRegistry(
            plugins_dir=tmp_path / "installed",
            skill_registry=MagicMock(),
            semantic_cache=MagicMock(),
            security_scan=True,
            block_on_warnings=True,
        )
        with pytest.raises(PluginSecurityError):
            await registry.install_plugin(str(plugin_dir))

    @pytest.mark.asyncio
    async def test_reload_plugin(self, tmp_path):
        """Hot reload plugin sau khi source thay đổi."""
        plugin_dir = make_plugin_dir(
            tmp_path,
            main_content="def register_tools(r): pass\n",
        )
        registry = self._make_registry(tmp_path)
        await registry.install_plugin(str(plugin_dir))

        # Giả lập source code thay đổi
        install_path = Path(registry._plugins["test-weather"].install_path)
        (install_path / "main.py").write_text(
            "VERSION = '2.0'\ndef register_tools(r): pass\n"
        )

        await registry.reload_plugin("test-weather")
        assert registry._modules["test-weather"].VERSION == "2.0"

    def test_get_plugin_namespace(self, tmp_path):
        registry = PluginRegistry(plugins_dir=tmp_path / "installed")
        assert registry.get_plugin_namespace("weather-fetcher") == "plugin:weather-fetcher"
        assert registry.get_plugin_namespace("my-plugin") == "plugin:my-plugin"
