"""
ironcore/channels/zalo_bot.py — Zalo Official Account (OA) Bot connector.

Zalo OA Webhook v3.0 integration:
  - Inbound events received via POST /webhooks/zalo (HMAC-SHA256 verified)
  - Outbound messages via Zalo OA API v2.0 (access_token bearer auth)
  - Auto access-token refresh via refresh_token

Features:
  - User text message → IronCore engine → reply in the same Zalo conversation
  - Image/attachment events → VLM pipeline (file_url forwarded)
  - Greeting/follow/unfollow events handled gracefully
  - Allowed-user OA-UID allowlist (empty = allow all)
  - Long responses chunked at Zalo 2000-char limit
  - Token auto-refresh: if access_token within 1-day of expiry, refresh

Env vars:
    ZALO_OA_ACCESS_TOKEN       — Current OA access token
    ZALO_OA_REFRESH_TOKEN      — Token to refresh when access_token expires
    ZALO_OA_APP_SECRET         — App secret for HMAC webhook verification
    ZALO_OA_ALLOWED_USER_IDS   — Optional comma-separated Zalo UIDs allowlist

Zalo OA API reference:
    https://developers.zalo.me/docs/api/official-account-api
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from ironcore.channels.base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)

# Zalo OA hard message length limit
_ZALO_MAX_LEN = 2000

# Zalo API base
_ZALO_API_BASE = "https://openapi.zalo.me"

# Event names that carry user text
_TEXT_EVENTS = {"user_send_text"}
# Event names that carry attachments
_ATTACHMENT_EVENTS = {"user_send_image", "user_send_file", "user_send_sticker"}
# Events to acknowledge but not route to engine
_META_EVENTS = {"follow", "unfollow", "user_submit_info", "oa_receive_gift"}


class ZaloTokenExpiredError(Exception):
    """Raised when the Zalo access token has expired and refresh failed."""


class ZaloChannel(BaseChannel):
    """
    Zalo OA connector — webhook-based (no long-polling).

    Unlike Telegram (which polls), Zalo pushes events to a webhook URL that
    your server must expose.  This class:
      1. Verifies inbound webhook signature.
      2. Parses Zalo event payloads into ChannelMessage.
      3. Dispatches to IronCoreEngine.
      4. Sends the reply back via Zalo OA API.

    For webhook receipt, wire ``handle_webhook_event(payload, mac_token)``
    into your FastAPI route:

        @router.post("/webhooks/zalo")
        async def zalo_webhook(request: Request):
            body = await request.body()
            mac = request.headers.get("X-ZaloOA-Signature", "")
            payload = json.loads(body)
            await zalo_channel.handle_webhook_event(payload, mac, raw_body=body)
            return {"status": "ok"}
    """

    MAX_MESSAGE_LEN = _ZALO_MAX_LEN

    def __init__(
        self,
        access_token: str,
        app_secret: str,
        refresh_token: str = "",
        allowed_user_ids: Optional[List[str]] = None,
        engine: Any = None,
    ) -> None:
        if not access_token:
            raise ValueError("Zalo access_token cannot be empty.")
        if not app_secret:
            raise ValueError("Zalo app_secret cannot be empty.")

        self._access_token = access_token
        self._refresh_token = refresh_token
        self._app_secret = app_secret
        self._allowed_user_ids: List[str] = allowed_user_ids or []
        self._engine = engine
        self._running = False

        # lazy HTTP client (aiohttp)
        self._session: Any = None

    # ── BaseChannel lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """
        For Zalo, "start" just opens the HTTP session — no long-polling.
        Webhook events are delivered via handle_webhook_event().
        """
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self._access_token}"}
            )
        except ImportError:
            raise ImportError(
                "aiohttp is required for ZaloChannel. "
                "Run: pip install aiohttp"
            )
        self._running = True
        logger.info("[Zalo] Channel started (webhook mode). Waiting for events...")

    async def stop(self) -> None:
        """Close the HTTP session."""
        self._running = False
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("[Zalo] Channel stopped.")

    # ── Sending messages ──────────────────────────────────────────────────────

    async def send_message(
        self, chat_id: str, text: str, reply_to: str = ""
    ) -> str:
        """
        Send a text message to a Zalo user (chat_id = Zalo user_id).
        Returns the Zalo message ID on success.
        """
        if not self._session:
            raise RuntimeError("ZaloChannel not started. Call start() first.")

        payload: Dict[str, Any] = {
            "recipient": {"user_id": chat_id},
            "message": {"text": text[:_ZALO_MAX_LEN]},
        }

        url = f"{_ZALO_API_BASE}/v2.0/oa/message/cs"
        async with self._session.post(url, json=payload) as resp:
            if resp.status == 401:
                # Try refreshing token
                refreshed = await self._refresh_access_token()
                if not refreshed:
                    raise ZaloTokenExpiredError("Zalo access token expired.")
                # Update session header and retry
                self._session.headers.update(
                    {"Authorization": f"Bearer {self._access_token}"}
                )
                async with self._session.post(url, json=payload) as retry:
                    data = await retry.json()
            else:
                data = await resp.json()

        if data.get("error") and data["error"] != 0:
            logger.error(
                "[Zalo] send_message error | code=%s msg=%s",
                data.get("error"),
                data.get("message"),
            )
            return ""

        return str(data.get("data", {}).get("message_id", ""))

    async def edit_message(
        self, chat_id: str, message_id: str, new_text: str
    ) -> None:
        """
        Zalo OA API does not support editing sent messages.
        This is a no-op; streaming simulation sends a follow-up message instead.
        """
        # Not supported by Zalo OA API — send a new message
        await self.send_message(chat_id, new_text)

    async def send_typing(self, chat_id: str) -> None:
        """
        Zalo OA does not have a typing indicator — send a short placeholder.
        """
        # No-op: Zalo OA doesn't expose a typing action endpoint
        pass

    # ── Webhook handling ──────────────────────────────────────────────────────

    def _verify_signature(self, raw_body: bytes, mac_token: str) -> bool:
        """
        Verify Zalo OA HMAC-SHA256 webhook signature.

        Zalo computes: HMAC_SHA256(app_secret, raw_body_bytes)
        and sends it in the X-ZaloOA-Signature header.
        """
        if not mac_token:
            logger.warning("[Zalo] Missing X-ZaloOA-Signature header.")
            return False
        expected = hmac.new(
            self._app_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, mac_token)

    async def handle_webhook_event(
        self,
        payload: Dict[str, Any],
        mac_token: str = "",
        raw_body: bytes = b"",
    ) -> None:
        """
        Process one inbound Zalo webhook event.

        Args:
            payload:   Parsed JSON body from Zalo.
            mac_token: Value of X-ZaloOA-Signature header (for HMAC check).
            raw_body:  Original raw request bytes (needed for HMAC).
        """
        # HMAC verification (skip if app_secret is empty — dev mode)
        if self._app_secret and raw_body:
            if not self._verify_signature(raw_body, mac_token):
                logger.warning("[Zalo] Webhook signature mismatch — event dropped.")
                return

        event_name: str = payload.get("event_name", "")
        sender_info: Dict[str, Any] = payload.get("sender", {})
        user_id: str = str(sender_info.get("id", ""))

        if not user_id:
            logger.debug("[Zalo] Webhook event with no sender.id, skipping.")
            return

        # Allowlist check
        if self._allowed_user_ids and user_id not in self._allowed_user_ids:
            logger.warning("[Zalo] Blocked user_id=%s (not in allowlist).", user_id)
            return

        if event_name in _META_EVENTS:
            await self._handle_meta_event(event_name, user_id, payload)
            return

        if event_name in _TEXT_EVENTS:
            await self._handle_text_event(user_id, payload)
            return

        if event_name in _ATTACHMENT_EVENTS:
            await self._handle_attachment_event(event_name, user_id, payload)
            return

        logger.debug("[Zalo] Unhandled event_name=%s", event_name)

    # ── Event handlers ────────────────────────────────────────────────────────

    async def _handle_text_event(
        self, user_id: str, payload: Dict[str, Any]
    ) -> None:
        """Route a plain-text message to the engine and reply."""
        message_block = payload.get("message", {})
        text: str = message_block.get("text", "").strip()
        msg_id: str = str(message_block.get("msg_id", ""))

        if not text:
            return

        # Send "..." placeholder then edit — Zalo doesn't support edit,
        # so we send placeholder then the real reply as a second message.
        placeholder_id = await self.send_message(user_id, "⏳ Đang xử lý...")

        msg = ChannelMessage(
            channel="zalo",
            user_id=user_id,
            chat_id=user_id,          # Zalo: direct OA→user, chat_id == user_id
            text=text,
            message_id=msg_id,
        )

        session_id = f"zalo:{user_id}"
        response = await self._dispatch_to_engine(self._engine, msg, session_id)

        # Delete placeholder by sending actual reply (Zalo can't edit messages)
        # Just send the real answer after the placeholder
        await self._send_chunked(user_id, response, reply_to=msg_id)

    async def _handle_attachment_event(
        self, event_name: str, user_id: str, payload: Dict[str, Any]
    ) -> None:
        """Route image/file attachments to the VLM pipeline."""
        message_block = payload.get("message", {})
        attachments: List[Dict[str, Any]] = message_block.get("attachments", [])
        msg_id: str = str(message_block.get("msg_id", ""))

        file_url = ""
        file_type = "document"
        for att in attachments:
            payload_att = att.get("payload", {})
            file_url = payload_att.get("url", payload_att.get("thumbnail", ""))
            if file_url:
                file_type = "image" if event_name == "user_send_image" else "document"
                break

        caption = message_block.get("text", f"[{event_name}]")

        msg = ChannelMessage(
            channel="zalo",
            user_id=user_id,
            chat_id=user_id,
            text=caption,
            file_url=file_url,
            file_type=file_type,
            message_id=msg_id,
        )

        await self.process_incoming(msg, self._engine)

    async def _handle_meta_event(
        self, event_name: str, user_id: str, payload: Dict[str, Any]
    ) -> None:
        """Handle follow/unfollow and other meta events."""
        if event_name == "follow":
            await self.send_message(
                user_id,
                "👋 Xin chào! Tôi là IronCore AI.\n"
                "Hãy nhắn tin để bắt đầu trò chuyện.",
            )
            logger.info("[Zalo] New follower: user_id=%s", user_id)
        elif event_name == "unfollow":
            logger.info("[Zalo] User unfollowed: user_id=%s", user_id)

    # ── Token management ──────────────────────────────────────────────────────

    async def _refresh_access_token(self) -> bool:
        """
        Refresh the Zalo access_token using refresh_token.
        Updates self._access_token on success.
        Returns True on success, False on failure.
        """
        if not self._refresh_token:
            logger.error("[Zalo] No refresh_token configured — cannot refresh.")
            return False

        # Zalo token refresh endpoint
        url = f"{_ZALO_API_BASE}/v3/access_token"
        import aiohttp
        async with aiohttp.ClientSession() as tmp:
            async with tmp.post(
                url,
                json={
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            ) as resp:
                data = await resp.json()

        if data.get("error") and data["error"] != 0:
            logger.error("[Zalo] Token refresh failed: %s", data.get("message"))
            return False

        new_token = data.get("access_token", "")
        new_refresh = data.get("refresh_token", "")
        if not new_token:
            return False

        self._access_token = new_token
        if new_refresh:
            self._refresh_token = new_refresh
        logger.info("[Zalo] Access token refreshed successfully.")
        return True

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, engine: Any = None) -> "ZaloChannel":
        """
        Build a ZaloChannel from environment variables.

        Required env vars:
            ZALO_OA_ACCESS_TOKEN
            ZALO_OA_APP_SECRET

        Optional env vars:
            ZALO_OA_REFRESH_TOKEN
            ZALO_OA_ALLOWED_USER_IDS  — comma-separated Zalo UIDs
        """
        token = os.getenv("ZALO_OA_ACCESS_TOKEN", "").strip()
        secret = os.getenv("ZALO_OA_APP_SECRET", "").strip()
        if not token:
            raise ValueError("ZALO_OA_ACCESS_TOKEN environment variable is not set.")
        if not secret:
            raise ValueError("ZALO_OA_APP_SECRET environment variable is not set.")

        refresh = os.getenv("ZALO_OA_REFRESH_TOKEN", "").strip()

        raw_ids = os.getenv("ZALO_OA_ALLOWED_USER_IDS", "").strip()
        allowed: List[str] = [p.strip() for p in raw_ids.split(",") if p.strip()] if raw_ids else []

        return cls(
            access_token=token,
            app_secret=secret,
            refresh_token=refresh,
            allowed_user_ids=allowed,
            engine=engine,
        )
