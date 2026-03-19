"""
IronCore V2: Plugin Registry
==============================
Phase 1 — The Architect (Gemini 3.1)

PluginRegistry là entry point cho toàn bộ plugin system:
  - install_plugin()   — end-to-end flow: download → validate → scan → import → register
  - uninstall_plugin() — unregister tools + xóa files + invalidate cache
  - enable_plugin()    — activate disabled plugin
  - disable_plugin()   — tắt plugin tạm thời
  - reload_plugin()    — hot-reload sau OTA update (atomic swap)
  - list_plugins()     — danh sách plugins đã cài
  - get_plugin_status() — trạng thái một plugin cụ thể
  - get_plugin_namespace() — để Claude gọi cache invalidation

Interface exported cho các agents khác:
  - PluginRegistry.install_plugin(source_url, requester_id) -> PluginManifest
  - PluginRegistry.uninstall_plugin(plugin_id) -> None
  - PluginRegistry.get_plugin_namespace(plugin_id) -> str
  - PluginRegistry.list_plugins() -> List[PluginInfo]

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .loader import PluginLoader
from .manifest import (
    ManifestValidationError,
    PluginError,
    PluginInfo,
    PluginInstallError,
    PluginManifest,
    PluginNotFoundError,
    PluginSecurityError,
    PluginStatus,
)

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Quản lý lifecycle của tất cả plugins được cài đặt vào IronCore.

    Thread-safe qua asyncio.Lock.

    Args:
        plugins_dir:       Thư mục cài plugin (mặc định: ironcore/plugins/installed)
        skill_registry:    SkillRegistry instance để register/unregister tools
        semantic_cache:    SemanticCache instance để invalidate khi plugin thay đổi
        security_scan:     True = scan security trước khi install (khuyến nghị)
        block_on_warnings: True = từ chối install nếu có security warnings
    """

    def __init__(
        self,
        plugins_dir: Optional[Path] = None,
        skill_registry: Optional[Any] = None,
        semantic_cache: Optional[Any] = None,
        security_scan: bool = True,
        block_on_warnings: bool = False,
    ) -> None:
        self._plugins_dir = plugins_dir or Path(
            os.getenv("IRONCORE_PLUGINS_DIR", "ironcore/plugins/installed")
        )
        self._plugins_dir.mkdir(parents=True, exist_ok=True)

        self._loader = PluginLoader(self._plugins_dir)
        self._skill_registry = skill_registry
        self._semantic_cache = semantic_cache
        self._security_scan = security_scan
        self._block_on_warnings = block_on_warnings

        # Runtime state: plugin_id → PluginInfo
        self._plugins: Dict[str, PluginInfo] = {}
        self._lock = asyncio.Lock()

        # Module references: plugin_id → imported module object
        self._modules: Dict[str, Any] = {}

        logger.info(
            "[PluginRegistry] Initialized | plugins_dir=%s scan=%s",
            self._plugins_dir,
            self._security_scan,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Install / Uninstall
    # ──────────────────────────────────────────────────────────────────────────

    async def install_plugin(
        self,
        source_url: str,
        requester_id: str = "",
    ) -> PluginManifest:
        """
        End-to-end plugin installation flow.

        Steps:
          1. download_plugin()        — tải về plugins_dir
          2. load_manifest()          — validate manifest.json
          3. scan_security()          — AST scan (nếu enabled)
          4. install_requirements()   — pip install
          5. dynamic_import()         — import module
          6. register_tools()         — đăng ký vào SkillRegistry
          7. invalidate_cache()       — notify SemanticCache

        Args:
            source_url:   GitHub URL, local path, hoặc marketplace ID
            requester_id: Định danh người/agent yêu cầu install (audit log)

        Returns:
            PluginManifest của plugin vừa cài.

        Raises:
            ManifestValidationError : manifest sai
            PluginSecurityError     : security scan phát hiện vấn đề nghiêm trọng
            PluginInstallError      : các lỗi khác trong quá trình install
        """
        logger.info(
            "[PluginRegistry] install_plugin START | source=%r requester=%s",
            source_url,
            requester_id,
        )

        async with self._lock:
            # ── Step 1: Download ───────────────────────────────────────────────
            plugin_dir = await self._loader.download_plugin(source_url)

            # ── Step 2: Load Manifest ─────────────────────────────────────────
            manifest = self._loader.load_manifest(plugin_dir)

            # Nếu plugin đã install, thực hiện upgrade thay vì cài đè
            if manifest.id in self._plugins:
                logger.info(
                    "[PluginRegistry] Plugin '%s' đã tồn tại — tiến hành upgrade",
                    manifest.id,
                )
                # Unregister tools cũ trước
                await self._unregister_tools(manifest.id)

            # ── Step 3: Security Scan ─────────────────────────────────────────
            security_warnings: List[str] = []
            if self._security_scan:
                security_warnings = self._loader.scan_security(plugin_dir, manifest)
                if security_warnings and self._block_on_warnings:
                    raise PluginSecurityError(
                        f"Plugin '{manifest.id}' bị từ chối do security warnings:\n"
                        + "\n".join(f"  - {w}" for w in security_warnings)
                    )

            # ── Step 4: Install Requirements ──────────────────────────────────
            await self._loader.install_requirements(plugin_dir, manifest)

            # ── Step 5: Dynamic Import ────────────────────────────────────────
            module = self._loader.dynamic_import(plugin_dir, manifest)
            self._modules[manifest.id] = module

            # ── Step 6: Register Tools ────────────────────────────────────────
            registered_tools = await self._register_tools(module, manifest)

            # ── Step 7: Invalidate Cache ──────────────────────────────────────
            await self._invalidate_cache(manifest.id)

            # ── Update State ──────────────────────────────────────────────────
            plugin_info = PluginInfo(
                manifest=manifest,
                status=PluginStatus.ACTIVE,
                installed_at=time.time(),
                install_path=str(plugin_dir),
                tools_registered=registered_tools,
                security_warnings=security_warnings,
            )
            self._plugins[manifest.id] = plugin_info

            logger.info(
                "[PluginRegistry] install_plugin DONE | id=%s tools=%s",
                manifest.id,
                registered_tools,
            )
            return manifest

    async def uninstall_plugin(self, plugin_id: str) -> None:
        """
        Gỡ bỏ plugin hoàn toàn.

        Steps:
          1. Unregister tools khỏi SkillRegistry
          2. Unload module khỏi sys.modules
          3. Xóa files trong plugins_dir
          4. Invalidate SemanticCache

        Args:
            plugin_id: ID của plugin cần gỡ

        Raises:
            PluginNotFoundError: khi plugin_id không tồn tại
        """
        logger.info("[PluginRegistry] uninstall_plugin | id=%s", plugin_id)

        async with self._lock:
            if plugin_id not in self._plugins:
                raise PluginNotFoundError(
                    f"Plugin '{plugin_id}' không tồn tại trong registry."
                )

            plugin_info = self._plugins[plugin_id]

            # ── Step 1: Unregister Tools ──────────────────────────────────────
            await self._unregister_tools(plugin_id)

            # ── Step 2: Unload Module ─────────────────────────────────────────
            self._loader.unload_module(plugin_id)
            self._modules.pop(plugin_id, None)

            # ── Step 3: Delete Files ──────────────────────────────────────────
            install_path = Path(plugin_info.install_path)
            if install_path.exists():
                shutil.rmtree(install_path, ignore_errors=True)
                logger.info(
                    "[PluginRegistry] Files xóa xong | path=%s",
                    install_path,
                )

            # ── Step 4: Invalidate Cache ──────────────────────────────────────
            await self._invalidate_cache(plugin_id)

            # ── Remove State ──────────────────────────────────────────────────
            del self._plugins[plugin_id]

            logger.info("[PluginRegistry] uninstall_plugin DONE | id=%s", plugin_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Enable / Disable
    # ──────────────────────────────────────────────────────────────────────────

    async def enable_plugin(self, plugin_id: str) -> None:
        """
        Kích hoạt lại plugin đã bị disable.
        Re-register tools vào SkillRegistry.

        Raises:
            PluginNotFoundError: plugin không tồn tại
            PluginInstallError:  plugin đang ở trạng thái ERROR
        """
        async with self._lock:
            plugin_info = self._get_plugin_or_raise(plugin_id)

            if plugin_info.status == PluginStatus.ACTIVE:
                logger.info("[PluginRegistry] Plugin '%s' đã ACTIVE rồi.", plugin_id)
                return

            if plugin_info.status == PluginStatus.ERROR:
                raise PluginInstallError(
                    f"Plugin '{plugin_id}' đang ở trạng thái ERROR. "
                    "Hãy uninstall và install lại."
                )

            module = self._modules.get(plugin_id)
            if module is None:
                raise PluginInstallError(
                    f"Module của plugin '{plugin_id}' không còn trong memory. "
                    "Hãy reload hoặc reinstall."
                )

            registered_tools = await self._register_tools(module, plugin_info.manifest)
            plugin_info.status = PluginStatus.ACTIVE
            plugin_info.tools_registered = registered_tools

            logger.info("[PluginRegistry] Plugin enabled | id=%s", plugin_id)

    async def disable_plugin(self, plugin_id: str) -> None:
        """
        Tắt plugin tạm thời mà không xóa files.
        Unregister tools khỏi SkillRegistry.

        Raises:
            PluginNotFoundError: plugin không tồn tại
        """
        async with self._lock:
            plugin_info = self._get_plugin_or_raise(plugin_id)

            if plugin_info.status == PluginStatus.DISABLED:
                logger.info("[PluginRegistry] Plugin '%s' đã DISABLED rồi.", plugin_id)
                return

            await self._unregister_tools(plugin_id)
            plugin_info.status = PluginStatus.DISABLED

            logger.info("[PluginRegistry] Plugin disabled | id=%s", plugin_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Hot Reload (dùng bởi OTA Update — Phase 2)
    # ──────────────────────────────────────────────────────────────────────────

    async def reload_plugin(self, plugin_id: str) -> None:
        """
        Hot-reload plugin sau khi source code được update (OTA).

        Đảm bảo atomic swap: tools mới được register trước khi tools cũ bị unregister.

        Args:
            plugin_id: ID plugin cần reload

        Raises:
            PluginNotFoundError: plugin không tồn tại
            PluginInstallError:  reload thất bại
        """
        logger.info("[PluginRegistry] reload_plugin | id=%s", plugin_id)

        async with self._lock:
            plugin_info = self._get_plugin_or_raise(plugin_id)
            install_path = Path(plugin_info.install_path)

            # Reload manifest (có thể đã thay đổi sau OTA)
            try:
                new_manifest = self._loader.load_manifest(install_path)
            except ManifestValidationError as exc:
                plugin_info.status = PluginStatus.ERROR
                plugin_info.error_message = str(exc)
                raise PluginInstallError(
                    f"reload_plugin thất bại: manifest mới không hợp lệ: {exc}"
                ) from exc

            # Security scan lại
            if self._security_scan:
                warnings = self._loader.scan_security(install_path, new_manifest)
                if warnings and self._block_on_warnings:
                    plugin_info.status = PluginStatus.ERROR
                    plugin_info.error_message = f"Security warnings: {warnings}"
                    raise PluginSecurityError(
                        f"reload thất bại: security warnings trong bản update."
                    )
                plugin_info.security_warnings = warnings

            # Unload cũ, import mới
            self._loader.unload_module(plugin_id)
            try:
                new_module = self._loader.dynamic_import(install_path, new_manifest)
            except PluginInstallError as exc:
                plugin_info.status = PluginStatus.ERROR
                plugin_info.error_message = str(exc)
                raise

            # Atomic swap: unregister cũ → register mới
            await self._unregister_tools(plugin_id)
            self._modules[plugin_id] = new_module
            registered_tools = await self._register_tools(new_module, new_manifest)

            # Invalidate cache
            await self._invalidate_cache(plugin_id)

            # Update state
            plugin_info.manifest = new_manifest
            plugin_info.status = PluginStatus.ACTIVE
            plugin_info.tools_registered = registered_tools
            plugin_info.error_message = None

            logger.info("[PluginRegistry] reload_plugin DONE | id=%s", plugin_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Query
    # ──────────────────────────────────────────────────────────────────────────

    async def list_plugins(self) -> List[PluginInfo]:
        """
        Trả về danh sách tất cả plugins đã cài (mọi trạng thái).
        Sắp xếp theo plugin_id alphabetically.
        """
        async with self._lock:
            return sorted(self._plugins.values(), key=lambda p: p.plugin_id)

    async def get_plugin_status(self, plugin_id: str) -> PluginStatus:
        """
        Trạng thái hiện tại của một plugin.

        Raises:
            PluginNotFoundError: plugin không tồn tại
        """
        async with self._lock:
            plugin_info = self._get_plugin_or_raise(plugin_id)
            return plugin_info.status

    def get_plugin_namespace(self, plugin_id: str) -> str:
        """
        Trả về namespace string để Claude dùng khi invalidate cache.

        Được thiết kế như interface static — không cần async.

        Returns:
            str: "plugin:{plugin_id}"
        """
        return f"plugin:{plugin_id}"

    # ──────────────────────────────────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_plugin_or_raise(self, plugin_id: str) -> PluginInfo:
        """Lấy PluginInfo hoặc raise PluginNotFoundError."""
        if plugin_id not in self._plugins:
            raise PluginNotFoundError(
                f"Plugin '{plugin_id}' không tồn tại trong registry."
            )
        return self._plugins[plugin_id]

    async def _register_tools(
        self,
        module: Any,
        manifest: PluginManifest,
    ) -> List[str]:
        """
        Gọi module.register_tools(skill_registry) để đăng ký tools.

        Returns:
            Danh sách tên tools đã được đăng ký thành công.
        """
        if self._skill_registry is None:
            logger.warning(
                "[PluginRegistry] skill_registry không có — tools của '%s' "
                "KHÔNG được đăng ký. Set skill_registry để enable.",
                manifest.id,
            )
            return [t.name for t in manifest.tools]

        registered: List[str] = []
        try:
            register_fn = getattr(module, "register_tools")
            if asyncio.iscoroutinefunction(register_fn):
                await register_fn(self._skill_registry)
            else:
                register_fn(self._skill_registry)

            # Xác nhận tools đã được register bằng cách check registry
            for tool_spec in manifest.tools:
                skill = self._skill_registry.get(tool_spec.name)
                if skill is not None:
                    registered.append(tool_spec.name)
                else:
                    logger.warning(
                        "[PluginRegistry] Tool '%s' được khai báo trong manifest "
                        "nhưng không có trong SkillRegistry sau khi register.",
                        tool_spec.name,
                    )

        except Exception as exc:
            raise PluginInstallError(
                f"Plugin '{manifest.id}' register_tools() thất bại: {exc}"
            ) from exc

        logger.info(
            "[PluginRegistry] Tools registered | plugin=%s tools=%s",
            manifest.id,
            registered,
        )
        return registered

    async def _unregister_tools(self, plugin_id: str) -> None:
        """Unregister tất cả tools của plugin khỏi SkillRegistry."""
        plugin_info = self._plugins.get(plugin_id)
        if not plugin_info or self._skill_registry is None:
            return

        for tool_name in plugin_info.tools_registered:
            try:
                await self._skill_registry.unregister(tool_name)
            except Exception as exc:
                # Log nhưng không raise — tiếp tục unregister các tools khác
                logger.warning(
                    "[PluginRegistry] Không unregister được tool '%s': %s",
                    tool_name,
                    exc,
                )

    async def _invalidate_cache(self, plugin_id: str) -> None:
        """Notify SemanticCache invalidate namespace của plugin."""
        if self._semantic_cache is None:
            return
        namespace = self.get_plugin_namespace(plugin_id)
        try:
            await self._semantic_cache.invalidate_namespace(namespace)
            logger.info(
                "[PluginRegistry] Cache invalidated | namespace=%s",
                namespace,
            )
        except Exception as exc:
            # Cache invalidation thất bại không nên block install
            logger.warning(
                "[PluginRegistry] Cache invalidation thất bại | namespace=%s error=%s",
                namespace,
                exc,
            )
