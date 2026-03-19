"""
ironcore/channels/messenger_bot.py — Facebook Messenger Bot connector.

Facebook Messenger Platform (webhook-based):
  - Inbound events via POST /v1/webhooks/messenger (HMAC-SHA256 verified)
  - Outbound via Graph API: POST https://graph.facebook.com/v18.0/me/messages
  - Webhook GET verification (Facebook sends GET with hub.challenge)

Features:
  - User text message → IronCore engine → reply in same Messenger thread
  - Quick replies and attachments acknowledged gracefully
  - Allowed-user (PSID) allowlist (empty = allow all)
  - Long responses chunked at Messenger 2000-char limit
  - Typing indicator via sender_action

Env vars:
    MESSENGER_PAGE_ACCESS_TOKEN  — From Meta Developer Console → Messenger → Page token
    MESSENGER_VERIFY_TOKEN       — Custom string you set in webhook settings
    MESSENGER_APP_SECRET         — For HMAC-SHA256 webhook signature verification

Reference: https://developers.facebook.com/docs/messenger-platform
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, List, Optional

from ironcore.channels.base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)

_MESSENGER_MAX_LEN = 2000
_GRAPH_API = "https://graph.facebook.com/v18.0"


class MessengerChannel(BaseChannel):
    """
    Facebook Messenger connector (webhook mode).

    Wire ``handle_webhook_event`` into:
        POST /v1/webhooks/messenger   ← inbound messages
        GET  /v1/webhooks/messenger   ← Facebook hub.challenge verification
    """

    MAX_MESSAGE_LEN = _MESSENGER_MAX_LEN

    def __init__(
        self,
        page_access_token: str,
        verify_token: str,
        app_secret: str = "",
        allowed_psids: Optional[List[str]] = None,
        engine: Any = None,
    ) -> None:
        if not page_access_token:
            raise ValueError("MESSENGER_PAGE_ACCESS_TOKEN cannot be empty.")
        if not verify_token:
            raise ValueError("MESSENGER_VERIFY_TOKEN cannot be empty.")

        self._page_token = page_access_token
        self._verify_token = verify_token
        self._app_secret = app_secret
        self._allowed_psids: List[str] = allowed_psids or []
        self._engine = engine
        self._running = False
        self._session: Any = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        try:
            import aiohttp
            self._session = aiohttp.ClientSession()
        except ImportError:
            raise ImportError("aiohttp is required. Run: pip install aiohttp")
        self._running = True
        logger.info("[Messenger] Channel started (webhook mode).")

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("[Messenger] Channel stopped.")

    # ── Sending ───────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> str:
        """Send a text message to a Messenger PSID."""
        if not self._session:
            raise RuntimeError("MessengerChannel not started.")

        payload = {
            "recipient": {"id": chat_id},
            "message": {"text": text[:_MESSENGER_MAX_LEN]},
            "messaging_type": "RESPONSE",
        }

        url = f"{_GRAPH_API}/me/messages?access_token={self._page_token}"
        async with self._session.post(url, json=payload) as resp:
            data = await resp.json()

        if "error" in data:
            logger.error("[Messenger] send_message error: %s", data["error"])
            return ""
        return str(data.get("message_id", ""))

    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None:
        """Messenger doesn't support editing — send a new message instead."""
        await self.send_message(chat_id, new_text)

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator via sender_action."""
        if not self._session:
            return
        payload = {
            "recipient": {"id": chat_id},
            "sender_action": "typing_on",
        }
        url = f"{_GRAPH_API}/me/messages?access_token={self._page_token}"
        try:
            async with self._session.post(url, json=payload):
                pass
        except Exception as exc:
            logger.debug("[Messenger] send_typing failed: %s", exc)

    # ── Webhook handling ──────────────────────────────────────────────────────

    def verify_hub_challenge(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """
        Verify the Facebook hub.challenge GET probe.
        Returns the challenge string if valid, else None.
        """
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    def _verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify X-Hub-Signature-256 header."""
        if not self._app_secret:
            return True  # dev mode: skip
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            self._app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature[7:])

    async def handle_webhook_event(
        self,
        payload: Dict[str, Any],
        signature: str = "",
        raw_body: bytes = b"",
    ) -> None:
        """Process one inbound Messenger webhook payload (may contain multiple messaging events)."""
        if self._app_secret and raw_body:
            if not self._verify_signature(raw_body, signature):
                logger.warning("[Messenger] Signature mismatch — dropped.")
                return

        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = str(event.get("sender", {}).get("id", ""))
                if not sender_id:
                    continue

                if self._allowed_psids and sender_id not in self._allowed_psids:
                    logger.warning("[Messenger] Blocked PSID=%s", sender_id)
                    continue

                # Text message
                if "message" in event and not event["message"].get("is_echo"):
                    text = event["message"].get("text", "").strip()
                    if text:
                        await self._handle_text(sender_id, text, event)

                # Postback (quick reply button taps)
                elif "postback" in event:
                    payload_str = event["postback"].get("payload", "")
                    title = event["postback"].get("title", payload_str)
                    await self._handle_text(sender_id, title or payload_str, event)

    async def _handle_text(self, psid: str, text: str, event: Dict[str, Any]) -> None:
        await self.send_typing(psid)
        msg = ChannelMessage(
            channel="messenger",
            user_id=psid,
            chat_id=psid,
            text=text,
            message_id=str(event.get("message", {}).get("mid", "")),
        )
        session_id = f"messenger:{psid}"
        response = await self._dispatch_to_engine(self._engine, msg, session_id)
        await self._send_chunked(psid, response)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, engine: Any = None) -> "MessengerChannel":
        token = os.getenv("MESSENGER_PAGE_ACCESS_TOKEN", "").strip()
        verify = os.getenv("MESSENGER_VERIFY_TOKEN", "").strip()
        secret = os.getenv("MESSENGER_APP_SECRET", "").strip()
        if not token:
            raise ValueError("MESSENGER_PAGE_ACCESS_TOKEN not set.")
        if not verify:
            raise ValueError("MESSENGER_VERIFY_TOKEN not set.")
        raw_ids = os.getenv("MESSENGER_ALLOWED_PSIDS", "").strip()
        allowed = [p.strip() for p in raw_ids.split(",") if p.strip()] if raw_ids else []
        return cls(
            page_access_token=token,
            verify_token=verify,
            app_secret=secret,
            allowed_psids=allowed,
            engine=engine,
        )
