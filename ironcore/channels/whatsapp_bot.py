"""
ironcore/channels/whatsapp_bot.py — WhatsApp Business (Meta Cloud API) connector.

Meta Cloud API (WhatsApp Business):
  - Inbound events via POST /v1/webhooks/whatsapp (HMAC-SHA256 verified)
  - Outbound via Graph API: POST https://graph.facebook.com/v18.0/{phone_number_id}/messages
  - Webhook GET verification (Facebook sends GET with hub.challenge)

Features:
  - Text messages → IronCore engine → reply in same WhatsApp thread
  - Read receipts sent after message is processed
  - Allowed-phone allowlist (empty = allow all)
  - Long responses chunked at WhatsApp 4096-char limit
  - Template messages (simple text type)

Env vars:
    WHATSAPP_PHONE_NUMBER_ID  — WhatsApp Business phone number ID (from Meta Developer Console)
    WHATSAPP_ACCESS_TOKEN     — System user or page access token
    WHATSAPP_VERIFY_TOKEN     — Custom string set in webhook settings
    WHATSAPP_APP_SECRET       — For HMAC-SHA256 X-Hub-Signature-256 verification

Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, List, Optional

from ironcore.channels.base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)

_WHATSAPP_MAX_LEN = 4096
_GRAPH_API = "https://graph.facebook.com/v18.0"


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp Business connector via Meta Cloud API (webhook mode).

    Wire ``handle_webhook_event`` into:
        POST /v1/webhooks/whatsapp   ← inbound messages
        GET  /v1/webhooks/whatsapp   ← Facebook hub.challenge verification
    """

    MAX_MESSAGE_LEN = _WHATSAPP_MAX_LEN

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        verify_token: str,
        app_secret: str = "",
        allowed_phones: Optional[List[str]] = None,
        engine: Any = None,
    ) -> None:
        if not phone_number_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID cannot be empty.")
        if not access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN cannot be empty.")
        if not verify_token:
            raise ValueError("WHATSAPP_VERIFY_TOKEN cannot be empty.")

        self._phone_id = phone_number_id
        self._token = access_token
        self._verify_token = verify_token
        self._app_secret = app_secret
        self._allowed_phones: List[str] = allowed_phones or []
        self._engine = engine
        self._running = False
        self._session: Any = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self._token}"}
            )
        except ImportError:
            raise ImportError("aiohttp is required. Run: pip install aiohttp")
        self._running = True
        logger.info("[WhatsApp] Channel started (webhook mode).")

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("[WhatsApp] Channel stopped.")

    # ── Sending ───────────────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> str:
        """
        Send a text message to a WhatsApp number.
        chat_id: recipient phone number in E.164 format (e.g. "84901234567")
        """
        if not self._session:
            raise RuntimeError("WhatsAppChannel not started.")

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": chat_id,
            "type": "text",
            "text": {"preview_url": False, "body": text[:_WHATSAPP_MAX_LEN]},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}

        url = f"{_GRAPH_API}/{self._phone_id}/messages"
        async with self._session.post(url, json=payload) as resp:
            data = await resp.json()

        if "error" in data:
            logger.error("[WhatsApp] send_message error: %s", data["error"])
            return ""
        messages = data.get("messages", [{}])
        return str(messages[0].get("id", "") if messages else "")

    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None:
        """WhatsApp Cloud API doesn't support editing — send a new message."""
        await self.send_message(chat_id, new_text)

    async def mark_read(self, message_id: str) -> None:
        """Mark an inbound message as read."""
        if not self._session:
            return
        url = f"{_GRAPH_API}/{self._phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            async with self._session.post(url, json=payload):
                pass
        except Exception as exc:
            logger.debug("[WhatsApp] mark_read failed: %s", exc)

    # ── Webhook handling ──────────────────────────────────────────────────────

    def verify_hub_challenge(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verify Facebook hub.challenge GET. Returns challenge if valid, else None."""
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    def _verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify X-Hub-Signature-256 header."""
        if not self._app_secret:
            return True  # dev: skip verification
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
        """Process one inbound WhatsApp webhook payload."""
        if self._app_secret and raw_body:
            if not self._verify_signature(raw_body, signature):
                logger.warning("[WhatsApp] Signature mismatch — dropped.")
                return

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") != "messages":
                    continue

                for msg in value.get("messages", []):
                    from_phone = str(msg.get("from", "")).strip()
                    msg_id = str(msg.get("id", ""))

                    if self._allowed_phones and from_phone not in self._allowed_phones:
                        logger.warning("[WhatsApp] Blocked phone=%s", from_phone)
                        continue

                    await self.mark_read(msg_id)

                    msg_type = msg.get("type", "")
                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "").strip()
                        if text:
                            await self._handle_text(from_phone, text, msg_id)
                    elif msg_type in ("image", "document", "audio", "video"):
                        mime = msg.get(msg_type, {}).get("mime_type", msg_type)
                        await self._handle_text(
                            from_phone, f"[{mime} attachment]", msg_id
                        )
                    elif msg_type == "location":
                        loc = msg.get("location", {})
                        await self._handle_text(
                            from_phone,
                            f"Location: {loc.get('latitude', '?')},{loc.get('longitude', '?')}",
                            msg_id,
                        )

    async def _handle_text(self, phone: str, text: str, msg_id: str = "") -> None:
        channel_msg = ChannelMessage(
            channel="whatsapp",
            user_id=phone,
            chat_id=phone,
            text=text,
            message_id=msg_id,
        )
        session_id = f"whatsapp:{phone}"
        response = await self._dispatch_to_engine(self._engine, channel_msg, session_id)
        await self._send_chunked(phone, response)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, engine: Any = None) -> "WhatsAppChannel":
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
        verify = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
        secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()
        if not phone_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID not set.")
        if not token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN not set.")
        if not verify:
            raise ValueError("WHATSAPP_VERIFY_TOKEN not set.")
        raw_phones = os.getenv("WHATSAPP_ALLOWED_PHONES", "").strip()
        allowed = [p.strip() for p in raw_phones.split(",") if p.strip()] if raw_phones else []
        return cls(
            phone_number_id=phone_id,
            access_token=token,
            verify_token=verify,
            app_secret=secret,
            allowed_phones=allowed,
            engine=engine,
        )
