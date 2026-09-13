"""
IronCore Tool: File Operations
==============================
Read, write, and list files within the workspace.
Paths are restricted to allowed directories for security.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = os.environ.get("IRONCORE_WORKSPACE", "/tmp/ironcore-workspace")
_MAX_READ_SIZE = 1_000_000  # 1 MB
_MAX_WRITE_SIZE = 5_000_000  # 5 MB


def _resolve_safe_path(filepath: str) -> Path:
    """Resolve a path ensuring it stays within the workspace root."""
    root = Path(_WORKSPACE_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / filepath).resolve()
    if not str(target).startswith(str(root)):
        raise PermissionError(f"Path traversal denied: {filepath}")
    return target


@skill(
    name="file_read",
    version="1.0.0",
    description="Read the contents of a file from the workspace.",
    author="brain",
    tags=["file", "read", "workspace"],
    risk_level=RiskLevel.LOW,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(name="path", type="string", description="Relative file path within workspace", required=True),
        SkillParameterSchema(name="encoding", type="string", description="File encoding", required=False, default="utf-8"),
    ],
)
async def file_read(path: str, encoding: str = "utf-8") -> str:
    """Read a file from the workspace."""
    try:
        target = _resolve_safe_path(path)
        if not target.exists():
            return json.dumps({"error": f"File not found: {path}"})
        if not target.is_file():
            return json.dumps({"error": f"Not a file: {path}"})

        size = target.stat().st_size
        if size > _MAX_READ_SIZE:
            return json.dumps({"error": f"File too large: {size} bytes (max {_MAX_READ_SIZE})"})

        content = target.read_text(encoding=encoding)
        return json.dumps({
            "path": path,
            "size": size,
            "content": content,
        }, ensure_ascii=False)
    except PermissionError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": f"Read failed: {exc}"})


@skill(
    name="file_write",
    version="1.0.0",
    description="Write content to a file in the workspace. Creates directories if needed.",
    author="brain",
    tags=["file", "write", "workspace"],
    risk_level=RiskLevel.MEDIUM,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(name="path", type="string", description="Relative file path within workspace", required=True),
        SkillParameterSchema(name="content", type="string", description="Content to write", required=True),
        SkillParameterSchema(name="mode", type="string", description="'overwrite' or 'append'", required=False, default="overwrite"),
    ],
)
async def file_write(path: str, content: str, mode: str = "overwrite") -> str:
    """Write content to a file in the workspace."""
    try:
        if len(content) > _MAX_WRITE_SIZE:
            return json.dumps({"error": f"Content too large: {len(content)} bytes (max {_MAX_WRITE_SIZE})"})

        target = _resolve_safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            target.write_text(content, encoding="utf-8")

        return json.dumps({
            "path": path,
            "size": target.stat().st_size,
            "mode": mode,
            "status": "written",
        })
    except PermissionError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": f"Write failed: {exc}"})


@skill(
    name="file_list",
    version="1.0.0",
    description="List files and directories in a workspace path.",
    author="brain",
    tags=["file", "list", "workspace"],
    risk_level=RiskLevel.LOW,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(name="path", type="string", description="Relative directory path (empty for root)", required=False, default=""),
        SkillParameterSchema(name="recursive", type="bool", description="List recursively", required=False, default=False),
    ],
)
async def file_list(path: str = "", recursive: bool = False) -> str:
    """List contents of a directory in the workspace."""
    try:
        target = _resolve_safe_path(path)
        if not target.exists():
            return json.dumps({"error": f"Path not found: {path}"})
        if not target.is_dir():
            return json.dumps({"error": f"Not a directory: {path}"})

        entries = []
        if recursive:
            for p in sorted(target.rglob("*")):
                rel = p.relative_to(target)
                entries.append({
                    "name": str(rel),
                    "type": "dir" if p.is_dir() else "file",
                    "size": p.stat().st_size if p.is_file() else 0,
                })
                if len(entries) >= 500:
                    break
        else:
            for p in sorted(target.iterdir()):
                entries.append({
                    "name": p.name,
                    "type": "dir" if p.is_dir() else "file",
                    "size": p.stat().st_size if p.is_file() else 0,
                })

        return json.dumps({"path": path, "count": len(entries), "entries": entries}, ensure_ascii=False)
    except PermissionError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": f"List failed: {exc}"})
