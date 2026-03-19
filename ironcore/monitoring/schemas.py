from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class AuditLogEntry(BaseModel):
    seq: int = Field(..., ge=1)
    timestamp: float = Field(..., ge=0)
    event_type: str
    session_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    agent: str
    prev_hash: str
    entry_hash: str

    @field_validator("event_type", "session_id", "agent", "prev_hash", "entry_hash")
    @classmethod
    def not_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field cannot be empty")
        return normalized


class ChainVerificationResult(BaseModel):
    is_intact: bool
    verified_entries: int = Field(default=0, ge=0)
    broken_entry_seq: Optional[int] = None
    expected_prev_hash: Optional[str] = None
    actual_prev_hash: Optional[str] = None
    expected_entry_hash: Optional[str] = None
    actual_entry_hash: Optional[str] = None
    error: Optional[str] = None
