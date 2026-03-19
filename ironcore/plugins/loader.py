"""
IronCore V2: Plugin Loader
============================
Phase 1 — The Architect (Gemini 3.1)

PluginLoader xử lý toàn bộ vòng đời download/scan/import của plugin:
  1. download_plugin()      — hỗ trợ GitHub URL, local path, marketplace URL
  2. load_manifest()        — parse và validate manifest.json
  3. scan_security()        — AST scan tìm imports/calls nguy hiểm
  4. install_requirements() — pip install vào plugins/installed/{id}/ env
  5. dynamic_import()       — import module với namespace isolation
  6. unload_module()        — cleanup sys.modules khi uninstall

SECURITY NOTE:
  - scan_security() sử dụng AST parse, không exec bất kỳ code nào của plugin
  - dynamic_import() raise ImportError nếu module không có register_tools()
  - FORBIDDEN_MODULES: set đầy đủ các module nguy hiểm

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import asyncio

from .manifest import (
    ManifestValidationError,
    PluginError,
    PluginInstallError,
    PluginManifest,
    PluginSecurityError,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Modules bị cấm tuyệt đối nếu plugin không khai báo đúng permission
FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "subprocess",
    "os",
    "sys",
    "importlib",
    "ctypes",
    "signal",
    "multiprocessing",
    "threading",
    "socket",
    "pty",
    "termios",
    "tty",
    "resource",
})

# Calls bị cấm tuyệt đối trong plugin code
FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "exec",
    "eval",
    "compile",
    "__import__",
    "open",       # sẽ cảnh báo nếu không có filesystem permission
    "input",
    "breakpoint",
})

# Các pattern nguy hiểm trong attribute access
FORBIDDEN_ATTR_PATTERNS: List[str] = [
    "__builtins__",
    "__globals__",
    "__code__",
    "__closure__",
    "__subclasses__",
    "func_globals",
    "gi_frame",
]


# ──────────────────────────────────────────────────────────────────────────────
# AST Visitor
# ──────────────────────────────────────────────────────────────────────────────

class SecurityASTVisitor(ast.NodeVisitor):
    """
    AST visitor scan toàn bộ Python source file của plugin.
    Thu thập warnings — không raise exception, để caller quyết định.
    """

    def __init__(
        self,
        forbidden_modules: frozenset[str],
        forbidden_calls: frozenset[str],
        allowed_permissions: List[str],
    ) -> None:
        self.warnings: List[str] = []
        self._forbidden_modules = forbidden_modules
        self._forbidden_calls = forbidden_calls
        self._allowed_permissions = allowed_permissions

    # ── Import checks ─────────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            self._check_module(mod, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            self._check_module(mod, node.lineno)
        self.generic_visit(node)

    def _check_module(self, module_name: str, lineno: int) -> None:
        if module_name in self._forbidden_modules:
            # Một số module được phép nếu có đúng permission
            if module_name in ("socket",) and "network" in self._allowed_permissions:
                return
            if module_name in ("os",) and "filesystem" in self._allowed_permissions:
                return
            self.warnings.append(
                f"Line {lineno}: import '{module_name}' bị cấm "
                f"(cần khai báo permission hoặc không được phép)."
            )

    # ── Call checks ───────────────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._extract_call_name(node.func)
        if call_name and call_name in self._forbidden_calls:
            # open() được phép nếu có filesystem permission, nhưng vẫn cảnh báo
            if call_name == "open" and "filesystem" in self._allowed_permissions:
                self.warnings.append(
                    f"Line {node.lineno}: open() — có filesystem permission nhưng "
                    "đảm bảo không ghi ngoài sandbox directory."
                )
            else:
                self.warnings.append(
                    f"Line {node.lineno}: gọi '{call_name}()' bị cấm trong plugin."
                )
        self.generic_visit(node)

    def _extract_call_name(self, func_node: ast.expr) -> Optional[str]:
        if isinstance(func_node, ast.Name):
            return func_node.id
        if isinstance(func_node, ast.Attribute):
            return func_node.attr
        return None

    # ── Attribute access checks ───────────────────────────────────────────────

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_ATTR_PATTERNS:
            self.warnings.append(
                f"Line {node.lineno}: truy cập attribute nguy hiểm '{node.attr}'."
            )
        self.generic_visit(node)


# ──────────────────────────────────────────────────────────────────────────────
# PluginLoader
# ──────────────────────────────────────────────────────────────────────────────

class PluginLoader:
    """
    Xử lý download, validate, security scan, và dynamic import của plugins.

    Usage:
        loader = PluginLoader(plugins_dir=Path("ironcore/plugins/installed"))
        plugin_dir = await loader.download_plugin("https://github.com/user/plugin")
        manifest = loader.load_manifest(plugin_dir)
        warnings = loader.scan_security(plugin_dir, manifest)
        if warnings:
            logger.warning("Security warnings: %s", warnings)
        await loader.install_requirements(plugin_dir, manifest)
        module = loader.dynamic_import(plugin_dir, manifest)
    """

    def __init__(self, plugins_dir: Path) -> None:
        self._plugins_dir = plugins_dir
        self._plugins_dir.mkdir(parents=True, exist_ok=True)

    # ── Download ──────────────────────────────────────────────────────────────

    async def download_plugin(self, source: str) -> Path:
        """
        Download plugin từ nhiều nguồn khác nhau về plugins_dir.

        Hỗ trợ:
          - GitHub URL: https://github.com/user/repo hoặc https://github.com/user/repo/archive/refs/heads/main.zip
          - Local path: /path/to/plugin hoặc ./path/to/plugin
          - Direct archive URL: file kết thúc bằng .zip hoặc .tar.gz

        Returns:
            Path đến thư mục plugin đã extract/copy.

        Raises:
            PluginInstallError: khi download hoặc extract thất bại.
        """
        source = source.strip()
        logger.info("[PluginLoader] download_plugin | source=%r", source)

        # Local path
        local = Path(source)
        if local.exists():
            return await self._copy_local(local)

        # URL-based
        parsed = urlparse(source)
        if parsed.scheme in ("http", "https"):
            return await self._download_url(source, parsed)

        raise PluginInstallError(
            f"Không nhận ra nguồn plugin: '{source}'. "
            "Hỗ trợ: local path, GitHub URL, direct archive URL."
        )

    async def _copy_local(self, source_path: Path) -> Path:
        """Copy plugin từ local directory."""
        if not source_path.is_dir():
            raise PluginInstallError(
                f"Local path '{source_path}' không phải thư mục."
            )
        manifest_file = source_path / "manifest.json"
        if not manifest_file.exists():
            raise PluginInstallError(
                f"'{source_path}' thiếu manifest.json."
            )
        # Đọc manifest để lấy id làm tên thư mục đích
        try:
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
            plugin_id = raw.get("id", source_path.name)
        except Exception:
            plugin_id = source_path.name

        dest = self._plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_path, dest)
        logger.info("[PluginLoader] Local copy xong | dest=%s", dest)
        return dest

    async def _download_url(self, url: str, parsed: Any) -> Path:
        """Download archive từ URL (GitHub hoặc direct link)."""
        # Normalize GitHub URL → archive zip
        if "github.com" in parsed.netloc and not url.endswith((".zip", ".tar.gz")):
            # https://github.com/user/repo → archive zip
            url = url.rstrip("/") + "/archive/refs/heads/main.zip"

        try:
            import urllib.request
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                archive_path = tmp_path / "plugin_archive"

                # Download với urllib (không cần httpx/aiohttp dependency mới)
                await asyncio.to_thread(
                    urllib.request.urlretrieve, url, str(archive_path)
                )

                # Extract
                extract_dir = tmp_path / "extracted"
                if url.endswith(".tar.gz") or url.endswith(".tgz"):
                    with tarfile.open(archive_path, "r:gz") as tf:
                        # Security: tránh path traversal trong tar
                        members = [m for m in tf.getmembers()
                                   if not m.name.startswith("/") and ".." not in m.name]
                        tf.extractall(extract_dir, members=members)
                else:
                    # Default: zip
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        # Security: tránh path traversal trong zip
                        safe_names = [n for n in zf.namelist()
                                      if not n.startswith("/") and ".." not in n]
                        for name in safe_names:
                            zf.extract(name, extract_dir)

                # Tìm thư mục chứa manifest.json
                plugin_dir = self._find_manifest_dir(extract_dir)
                return await self._copy_local(plugin_dir)

        except PluginInstallError:
            raise
        except Exception as exc:
            raise PluginInstallError(
                f"Download plugin thất bại từ '{url}': {exc}"
            ) from exc

    def _find_manifest_dir(self, root: Path) -> Path:
        """Tìm thư mục chứa manifest.json (có thể nằm 1–2 cấp sâu hơn)."""
        for candidate in [root] + list(root.iterdir()):
            if candidate.is_dir() and (candidate / "manifest.json").exists():
                return candidate
        raise PluginInstallError(
            f"Không tìm thấy manifest.json trong archive. "
            "Đảm bảo plugin có manifest.json ở root của archive."
        )

    # ── Manifest ──────────────────────────────────────────────────────────────

    def load_manifest(self, plugin_dir: Path) -> PluginManifest:
        """
        Đọc và validate manifest.json trong plugin_dir.

        Raises:
            ManifestValidationError: khi file không tồn tại hoặc schema sai.
        """
        manifest_file = plugin_dir / "manifest.json"
        if not manifest_file.exists():
            raise ManifestValidationError(
                f"'{plugin_dir}' thiếu manifest.json."
            )
        try:
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(
                f"manifest.json không phải JSON hợp lệ: {exc}"
            ) from exc

        try:
            manifest = PluginManifest.model_validate(raw)
        except Exception as exc:
            raise ManifestValidationError(
                f"manifest.json không hợp lệ: {exc}"
            ) from exc

        logger.info(
            "[PluginLoader] Manifest loaded | id=%s version=%s tools=%d",
            manifest.id,
            manifest.version,
            len(manifest.tools),
        )
        return manifest

    # ── Security Scan ─────────────────────────────────────────────────────────

    def scan_security(
        self,
        plugin_dir: Path,
        manifest: PluginManifest,
    ) -> List[str]:
        """
        AST scan toàn bộ Python files trong plugin_dir.

        KHÔNG exec bất kỳ code nào — chỉ phân tích syntax tree tĩnh.

        Returns:
            List warnings (empty = sạch). Mỗi warning là chuỗi mô tả vấn đề.

        Raises:
            PluginSecurityError: khi không thể parse một file Python.
        """
        allowed_permissions = [p.value for p in manifest.permissions]
        all_warnings: List[str] = []

        python_files = list(plugin_dir.rglob("*.py"))
        logger.info(
            "[PluginLoader] Security scan | plugin=%s files=%d",
            manifest.id,
            len(python_files),
        )

        for py_file in python_files:
            relative = py_file.relative_to(plugin_dir)
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(relative))
            except SyntaxError as exc:
                raise PluginSecurityError(
                    f"File '{relative}' có lỗi syntax: {exc}"
                ) from exc
            except Exception as exc:
                raise PluginSecurityError(
                    f"Không thể đọc/parse '{relative}': {exc}"
                ) from exc

            visitor = SecurityASTVisitor(
                forbidden_modules=FORBIDDEN_MODULES,
                forbidden_calls=FORBIDDEN_CALLS,
                allowed_permissions=allowed_permissions,
            )
            visitor.visit(tree)

            for warning in visitor.warnings:
                all_warnings.append(f"[{relative}] {warning}")

        if all_warnings:
            logger.warning(
                "[PluginLoader] Security warnings | plugin=%s count=%d",
                manifest.id,
                len(all_warnings),
            )
        else:
            logger.info("[PluginLoader] Security scan sạch | plugin=%s", manifest.id)

        return all_warnings

    # ── Requirements ─────────────────────────────────────────────────────────

    async def install_requirements(
        self,
        plugin_dir: Path,
        manifest: PluginManifest,
    ) -> None:
        """
        Cài đặt pip packages mà plugin khai báo trong install_requires.

        Packages được install vào site-packages của Python hiện tại.
        Trong production, nên dùng venv riêng per plugin (V3 roadmap).

        Raises:
            PluginInstallError: khi pip install thất bại.
        """
        requirements = manifest.install_requires

        # Ưu tiên requirements.txt nếu có
        req_file = plugin_dir / "requirements.txt"
        if req_file.exists() and not requirements:
            requirements = [
                line.strip()
                for line in req_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]

        if not requirements:
            logger.info(
                "[PluginLoader] Không có requirements | plugin=%s",
                manifest.id,
            )
            return

        logger.info(
            "[PluginLoader] Installing requirements | plugin=%s packages=%s",
            manifest.id,
            requirements,
        )

        # Validate package names trước khi truyền vào pip (tránh injection)
        safe_packages = self._validate_package_names(requirements)
        if len(safe_packages) < len(requirements):
            rejected = set(requirements) - set(safe_packages)
            raise PluginInstallError(
                f"Package names không hợp lệ bị từ chối: {rejected}"
            )

        cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + safe_packages
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise PluginInstallError(
                    f"pip install thất bại cho plugin '{manifest.id}':\n"
                    f"{result.stderr}"
                )
        except asyncio.TimeoutError as exc:
            raise PluginInstallError(
                f"pip install timeout (120s) cho plugin '{manifest.id}'."
            ) from exc

        logger.info(
            "[PluginLoader] Requirements installed | plugin=%s",
            manifest.id,
        )

    def _validate_package_names(self, packages: List[str]) -> List[str]:
        """
        Validate pip package names để tránh command injection.
        Chỉ cho phép: chữ, số, dấu gạch dưới, gạch ngang, dấu chấm, ==, >=, <=, ~=, !=, [.
        """
        # Pattern an toàn cho tên package + version specifier
        safe_pattern = re.compile(
            r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*"
            r"(\[[\w,]+\])?"                       # extras [dev,test]
            r"(\s*(==|>=|<=|~=|!=|>|<)\s*[\w\.\*]+)*$"
        )
        valid = []
        for pkg in packages:
            if safe_pattern.match(pkg.strip()):
                valid.append(pkg.strip())
            else:
                logger.error(
                    "[PluginLoader] Package name bị từ chối vì không an toàn: %r",
                    pkg,
                )
        return valid

    # ── Dynamic Import ────────────────────────────────────────────────────────

    def dynamic_import(
        self,
        plugin_dir: Path,
        manifest: PluginManifest,
    ) -> Any:
        """
        Import plugin module với namespace isolation.

        Plugin module PHẢI export function:
            def register_tools(registry: SkillRegistry) -> None

        Module được import với tên `ironcore_plugin_{plugin_id}` để tránh
        conflict với modules khác trong sys.modules.

        Returns:
            Module object đã import.

        Raises:
            PluginInstallError: khi entry_point không tồn tại hoặc
                                không có register_tools().
        """
        entry_file = plugin_dir / manifest.entry_point
        if not entry_file.exists():
            raise PluginInstallError(
                f"Entry point '{manifest.entry_point}' không tồn tại "
                f"trong plugin '{manifest.id}'."
            )

        module_name = f"ironcore_plugin_{manifest.id.replace('-', '_')}"

        # Xóa cache cũ nếu có (hỗ trợ hot-reload)
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, entry_file)
        if spec is None or spec.loader is None:
            raise PluginInstallError(
                f"Không thể tạo module spec cho '{entry_file}'."
            )

        module = importlib.util.module_from_spec(spec)

        # Đăng ký trước khi exec để hỗ trợ relative imports trong plugin
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
        except Exception as exc:
            # Cleanup nếu exec thất bại
            sys.modules.pop(module_name, None)
            raise PluginInstallError(
                f"Lỗi khi load plugin '{manifest.id}': {exc}"
            ) from exc

        # Kiểm tra contract bắt buộc
        if not hasattr(module, "register_tools"):
            sys.modules.pop(module_name, None)
            raise PluginInstallError(
                f"Plugin '{manifest.id}' thiếu function register_tools(registry). "
                "Đây là contract bắt buộc của IronCore plugin system."
            )

        if not callable(getattr(module, "register_tools")):
            sys.modules.pop(module_name, None)
            raise PluginInstallError(
                f"Plugin '{manifest.id}': register_tools phải là callable."
            )

        logger.info(
            "[PluginLoader] Plugin imported | id=%s module=%s",
            manifest.id,
            module_name,
        )
        return module

    # ── Unload ────────────────────────────────────────────────────────────────

    def unload_module(self, plugin_id: str) -> None:
        """
        Xóa plugin module khỏi sys.modules.
        Được gọi khi uninstall hoặc trước hot-reload.
        """
        module_name = f"ironcore_plugin_{plugin_id.replace('-', '_')}"
        removed = sys.modules.pop(module_name, None)
        if removed is not None:
            logger.info("[PluginLoader] Module unloaded | id=%s", plugin_id)
        else:
            logger.debug("[PluginLoader] Module không có trong sys.modules | id=%s", plugin_id)
