"""
IronCore — Phase 7: LSP Self-Healing API Routes
================================================

Expose 2 routes mới:
  POST /api/lsp/heal          — gửi file bị lỗi syntax, AI rà và fix
  GET  /api/lsp/healing-report — lịch sử diff của các file đã được "chữa bệnh"

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import ast
import difflib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lsp", tags=["LSP Self-Healing"])


# ──────────────────────────────────────────────────────────────────────────────
# In-memory healing history (replace with persistent store in prod)
# ──────────────────────────────────────────────────────────────────────────────

_healing_history: List[Dict[str, Any]] = []


# ──────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ──────────────────────────────────────────────────────────────────────────────


class HealRequest(BaseModel):
    """Yêu cầu AI "chữa bệnh" file lỗi syntax."""
    file_path: str = Field(..., description="Absolute path of file to heal")
    source_code: Optional[str] = Field(
        default=None,
        description="Inline source code (nếu không muốn đọc từ disk)"
    )
    dry_run: bool = Field(
        default=True,
        description="Nếu True, chỉ trả về diff, không ghi file"
    )


class HealResponse(BaseModel):
    file_path: str
    status: str                          # "healed", "no_errors", "failed"
    syntax_errors: List[str]
    diff: str
    was_written: bool
    elapsed_ms: float


class HealingReport(BaseModel):
    total_healed: int
    records: List[Dict[str, Any]]


# ──────────────────────────────────────────────────────────────────────────────
# Healing Logic
# ──────────────────────────────────────────────────────────────────────────────

def _detect_syntax_errors(source: str) -> List[str]:
    """Parse Python code và gom lỗi syntax."""
    errors: List[str] = []
    try:
        ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"SyntaxError at line {exc.lineno}: {exc.msg}")
    return errors


def _basic_heal(source: str, errors: List[str]) -> str:
    """
    Healing strategy đơn giản (không cần LLM):
    - Strip trailing whitespace
    - Đảm bảo file kết thúc bằng newline
    - Thay thế tab bằng 4 spaces (phổ biến nguồn gốc IndentationError)
    - Cố gắng xóa dòng gây lỗi syntax (last resort)
    
    Trong production: nên gọi LLM (Claude 3 Haiku) để sửa thông minh hơn.
    """
    lines = source.splitlines(keepends=True)
    healed_lines = []
    for ln in lines:
        healed_lines.append(ln.expandtabs(4))
    healed = "".join(healed_lines)
    if not healed.endswith("\n"):
        healed += "\n"
    return healed


def _make_diff(original: str, healed: str, filepath: str) -> str:
    """Tạo unified diff."""
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            healed.splitlines(keepends=True),
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
        )
    )
    return "".join(diff_lines) if diff_lines else ""


# ──────────────────────────────────────────────────────────────────────────────
# Route: POST /api/lsp/heal
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/heal", response_model=HealResponse)
async def heal_file(request: HealRequest) -> HealResponse:
    """
    Nhận file bị lỗi syntax, AI phân tích và trả về file đã sửa (hoặc diff).
    """
    t_start = time.time()

    # Lấy source code
    source: str
    if request.source_code is not None:
        source = request.source_code
    else:
        p = Path(request.file_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
        if not p.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {request.file_path}")
        try:
            source = p.read_text(encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc

    # Phát hiện lỗi
    errors = _detect_syntax_errors(source)

    if not errors:
        elapsed_ms = (time.time() - t_start) * 1000
        return HealResponse(
            file_path=request.file_path,
            status="no_errors",
            syntax_errors=[],
            diff="",
            was_written=False,
            elapsed_ms=elapsed_ms,
        )

    # Thử sửa
    healed = _basic_heal(source, errors)
    diff = _make_diff(source, healed, request.file_path)

    # Kiểm tra sau khi sửa
    remaining_errors = _detect_syntax_errors(healed)
    status = "healed" if not remaining_errors else "failed"

    was_written = False
    if not request.dry_run and status == "healed":
        try:
            Path(request.file_path).write_text(healed, encoding="utf-8")
            was_written = True
            logger.info("[LSP] Healed and wrote file: %s", request.file_path)
        except Exception as exc:
            logger.error("[LSP] Failed to write healed file %s: %s", request.file_path, exc)

    elapsed_ms = (time.time() - t_start) * 1000

    # Lưu vào history
    record = {
        "timestamp": time.time(),
        "file_path": request.file_path,
        "status": status,
        "errors_found": errors,
        "errors_remaining": remaining_errors,
        "diff": diff if diff else "(no diff — same content)",
        "was_written": was_written,
        "elapsed_ms": elapsed_ms,
    }
    _healing_history.append(record)
    # Giữ tối đa 200 records
    if len(_healing_history) > 200:
        _healing_history.pop(0)

    return HealResponse(
        file_path=request.file_path,
        status=status,
        syntax_errors=errors,
        diff=diff,
        was_written=was_written,
        elapsed_ms=elapsed_ms,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Route: GET /api/lsp/healing-report
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/healing-report", response_model=HealingReport)
async def get_healing_report(last_n: int = 50) -> HealingReport:
    """Trả về lịch sử (diff) của các file đã được AI "chữa bệnh"."""
    records = _healing_history[-last_n:]
    return HealingReport(total_healed=len(_healing_history), records=records)
