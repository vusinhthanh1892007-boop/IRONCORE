"""
IronCore V2 — Webhook Data Models
===================================
Phase 4 — The Architect (Gemini 3.1)

Pydantic models for webhook registrations and events.
"""

from __future__ import annotations

import secrets
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WebhookSource(str, Enum):
    GITHUB = "github"
    STRIPE = "stripe"
    GITLAB = "gitlab"
    CUSTOM = "custom"


class WebhookRegistration(BaseModel):
    """A registered webhook endpoint with its configuration."""

    id: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    name: str = Field(..., description="Human-readable label, e.g. 'GitHub main repo'")
    source: WebhookSource
    # Secret used to verify HMAC signatures from the sender.
    # Store securely — never log this value.
    secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    # Trailing path component: /webhooks/{endpoint_suffix}
    endpoint_suffix: str = Field(
        ...,
        pattern=r"^[a-z0-9\-_]{3,80}$",
        description="URL-safe suffix for the inbound endpoint.",
    )
    target_actions: List[str] = Field(
        default_factory=list,
        description="IronCore action names to trigger on receipt.",
    )
    enabled: bool = True
    verify_signature: bool = True
    created_at: float = Field(default_factory=time.time)


class WebhookEvent(BaseModel):
    """A single inbound webhook event captured from an external source."""

    id: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    registration_id: str
    source: WebhookSource
    event_type: str = Field(
        ...,
        description="Platform-specific event type, e.g. 'push', 'pull_request', 'payment.succeeded'.",
    )
    delivery_id: Optional[str] = Field(
        None,
        description="Platform-supplied delivery ID used for replay-attack prevention.",
    )
    payload: Dict[str, Any] = Field(default_factory=dict)
    received_at: float = Field(default_factory=time.time)
    processed: bool = False
    error: Optional[str] = None
