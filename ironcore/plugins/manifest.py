"""
IronCore V2: Plugin Manifest Schema
====================================
Phase 1 — The Architect (Gemini 3.1)

Định nghĩa schema cho manifest.json của mỗi plugin.
Mọi plugin PHẢI có manifest.json hợp lệ trước khi được cài đặt.

Cấu trúc thư mục plugin sau khi cài:
  ironcore/plugins/installed/{plugin_id}/
  ├── manifest.json    ← file này validate
  ├── main.py          ← entry point (phải có register_tools(registry))
  └── requirements.txt ← pip deps (tùy chọn)

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────────

class PluginError(Exception):
    """Base exception cho toàn bộ plugin subsystem."""


class ManifestValidationError(PluginError):
    """Raised khi manifest.json không hợp lệ."""


class PluginSecurityError(PluginError):
    """Raised khi security scan phát hiện code nguy hiểm."""


class PluginInstallError(PluginError):
    """Raised khi quá trình cài đặt thất bại."""


class PluginNotFoundError(PluginError):
    """Raised khi plugin_id không tồn tại trong registry."""


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class PluginPermission(str, Enum):
    """
    Khai báo quyền hạn mà plugin cần.
    User phải xác nhận cấp từng permission trước khi install.
    """
    NETWORK = "network"         # Được phép gọi HTTP ra ngoài
    FILESYSTEM = "filesystem"   # Được phép đọc file hệ thống
    BROWSER = "browser"         # Được phép dùng browser module
    DATABASE = "database"       # Được phép query database trực tiếp


class PluginStatus(str, Enum):
    """Vòng đời của một plugin đã cài đặt."""
    INSTALLED = "installed"     # Cài xong, chưa activate
    ACTIVE = "active"           # Đang chạy bình thường
    DISABLED = "disabled"       # Tắt tạm thời (tools không khả dụng)
    ERROR = "error"             # Lỗi load/runtime


class PluginSource(str, Enum):
    """Nguồn gốc của plugin."""
    GITHUB = "github"
    LOCAL = "local"
    MARKETPLACE = "marketplace"
    URL = "url"


# ──────────────────────────────────────────────────────────────────────────────
# Sub-models
# ──────────────────────────────────────────────────────────────────────────────

class ToolSpec(BaseModel):
    """
    Khai báo một tool mà plugin cung cấp.
    Dùng để pre-validate trước khi import thực sự.
    """
    name: str = Field(description="Tên tool, phải là snake_case duy nhất")
    description: str = Field(description="Mô tả cho LLM hiểu")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema cho parameters",
    )
    returns: str = Field(default="str", description="Kiểu trả về")
    risk_level: str = Field(
        default="low",
        description="Mức độ rủi ro: low / medium / high",
    )

    @field_validator("name")
    @classmethod
    def name_must_be_snake_case(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_]*$", v.strip()):
            raise ValueError(
                f"Tool name '{v}' phải là snake_case "
                "(chữ thường, số, dấu gạch dưới; bắt đầu bằng chữ cái)."
            )
        return v.strip()

    @field_validator("risk_level")
    @classmethod
    def risk_level_valid(cls, v: str) -> str:
        allowed = {"low", "medium", "high"}
        if v.lower() not in allowed:
            raise ValueError(f"risk_level phải là một trong {allowed}")
        return v.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Main Manifest Model
# ──────────────────────────────────────────────────────────────────────────────

class PluginManifest(BaseModel):
    """
    Schema đầy đủ cho manifest.json của một plugin IronCore.

    Ví dụ manifest.json hợp lệ:
    {
        "id": "weather-fetcher",
        "name": "Weather Fetcher",
        "version": "1.0.0",
        "author": "user@example.com",
        "description": "Lấy thông tin thời tiết real-time",
        "ironcore_min_version": "2.0.0",
        "permissions": ["network"],
        "tools": [
            {
                "name": "get_weather",
                "description": "Lấy thời tiết hiện tại cho một địa điểm",
                "parameters": {"location": {"type": "string"}},
                "risk_level": "low"
            }
        ]
    }
    """

    id: str = Field(
        description="Plugin ID duy nhất, kebab-case",
        pattern=r"^[a-z0-9][a-z0-9\-]{2,49}$",
    )
    name: str = Field(description="Tên hiển thị của plugin")
    version: str = Field(description="Phiên bản semver X.Y.Z")
    author: str = Field(description="Email hoặc tên tác giả")
    description: str = Field(description="Mô tả ngắn (1 dòng)")
    long_description: str = Field(default="", description="Mô tả chi tiết")
    ironcore_min_version: str = Field(
        default="2.0.0",
        description="IronCore version tối thiểu yêu cầu",
    )
    permissions: List[PluginPermission] = Field(
        default_factory=list,
        description="Danh sách quyền hạn cần thiết",
    )
    tools: List[ToolSpec] = Field(
        default_factory=list,
        description="Danh sách tools plugin cung cấp",
    )
    entry_point: str = Field(
        default="main.py",
        description="File Python entry point (phải export register_tools)",
    )
    install_requires: List[str] = Field(
        default_factory=list,
        description="Danh sách pip packages cần install",
    )
    homepage: Optional[str] = Field(default=None, description="URL trang chủ plugin")
    license: str = Field(default="MIT", description="Giấy phép sử dụng")
    tags: List[str] = Field(default_factory=list, description="Tags phân loại")

    @field_validator("id")
    @classmethod
    def id_not_reserved(cls, v: str) -> str:
        """Namespace ironcore-core-* bị bảo lưu cho internal modules."""
        if v.startswith("ironcore-core"):
            raise ValueError(
                f"Plugin id '{v}' dùng Reserved namespace 'ironcore-core'. "
                "Chọn tên khác."
            )
        return v

    @field_validator("version")
    @classmethod
    def version_semver(cls, v: str) -> str:
        parts = v.strip().split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError(
                f"Version '{v}' phải theo định dạng semver: MAJOR.MINOR.PATCH "
                "(ví dụ: 1.0.0)"
            )
        return v.strip()

    @field_validator("tools")
    @classmethod
    def tools_names_unique(cls, v: List[ToolSpec]) -> List[ToolSpec]:
        names = [t.name for t in v]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(
                f"Tên tools bị trùng trong manifest: {duplicates}"
            )
        return v


# ──────────────────────────────────────────────────────────────────────────────
# Runtime Info Model (sau khi install)
# ──────────────────────────────────────────────────────────────────────────────

class PluginInfo(BaseModel):
    """
    Trạng thái runtime của một plugin đã cài đặt.
    Kết hợp manifest + metadata vận hành.
    """
    manifest: PluginManifest
    status: PluginStatus = PluginStatus.INSTALLED
    installed_at: float = 0.0
    install_path: str = ""
    tools_registered: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    security_warnings: List[str] = Field(default_factory=list)

    @property
    def plugin_id(self) -> str:
        return self.manifest.id

    @property
    def is_active(self) -> bool:
        return self.status == PluginStatus.ACTIVE
