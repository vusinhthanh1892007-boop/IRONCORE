"""
ironcore/channels/base.py — Abstract base class for all channel connectors.

Every channel (Telegram, Discord, etc.) shares:
  - ChannelMessage: typed inbound message model
  - BaseChannel: ABC with required interface methods
  - process_incoming: shared routing → engine → chunked response
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Maximum chars per message chunk (Telegram = 4096, Discord = 2000).
# Subclasses override via MAX_MESSAGE_LEN class attribute.
_DEFAULT_MAX_MESSAGE_LEN = 4096


class ChannelMessage(BaseModel):
    """Normalised inbound message from any channel platform."""

    channel: str                          # "telegram" | "discord"
    user_id: str                          # Platform-specific user identifier
    chat_id: str                          # Chat/channel/DM destination
    text: Optional[str] = None            # Plain text content (may be None for file-only)
    file_url: Optional[str] = None        # Pre-signed or direct file URL
    file_type: Optional[str] = None       # "document" | "image" | "audio"
    message_id: str = ""                  # Original platform message ID (for reply/edit)
    thread_id: Optional[str] = None       # Discord thread / Telegram topic ID


class BaseChannel(ABC):
    """
    Abstract base for all IronCore channel connectors.

    Lifecycle:
        await channel.start()     ← connect to platform, begin receiving
        await channel.stop()      ← graceful disconnect

    Sending:
        await channel.send_message(chat_id, text)
        await channel.edit_message(chat_id, message_id, new_text)
        await channel.send_typing(chat_id)

    Receiving:
        Platform-specific handler calls self.process_incoming(msg, engine)
    """

    # Subclasses override to enforce platform message length limit
    MAX_MESSAGE_LEN: int = _DEFAULT_MAX_MESSAGE_LEN

    # ── Abstract interface ─────────────────────────────────────────────────────

    @abstractmethod
    async def start(self) -> None:
        """Connect to the platform and begin processing incoming messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully disconnect and clean up resources."""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> str:
        """
        Send a new message.

        Returns:
            Platform message ID of the sent message (needed for edits/replies).
        """

    @abstractmethod
    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None:
        """Edit an already-sent message (used for streaming simulation)."""

    @abstractmethod
    async def send_typing(self, chat_id: str) -> None:
        """Send typing/processing indicator to the chat."""

    # ── Shared logic ──────────────────────────────────────────────────────────

    async def process_incoming(self, msg: ChannelMessage, engine: Any) -> None:
        """
        Shared routing logic for all channels:
          1. Build session_id as "{channel}:{user_id}"
          2. Send typing indicator
          3. Dispatch to engine
          4. Send chunked response

        The engine must expose:
            async def process_message(text: str, session_id: str) -> str
        or be a plain async callable(text, session_id) -> str.
        """
        session_id = f"{msg.channel}:{msg.user_id}"
        logger.info(
            "[%s] Incoming | session=%s chat=%s text_len=%s",
            msg.channel.upper(),
            session_id,
            msg.chat_id,
            len(msg.text or ""),
        )

        await self.send_typing(msg.chat_id)

        response_text = await self._dispatch_to_engine(engine, msg, session_id)
        await self._send_chunked(msg.chat_id, response_text, reply_to=msg.message_id)

    async def _dispatch_to_engine(
        self, engine: Any, msg: ChannelMessage, session_id: str
    ) -> str:
        """Route the message to the engine and return the text response."""
        if engine is None:
            return "IronCore engine not connected. Please try again later."

        text = msg.text or ""

        try:
            if hasattr(engine, "process_message"):
                # Preferred interface: async process_message(text, session_id)
                result = await engine.process_message(text, session_id)
            elif callable(engine):
                result = await engine(text, session_id)
            else:
                logger.warning("[BaseChannel] Unknown engine type: %s", type(engine))
                return "Engine interface error. Contact admin."

            return str(result) if result is not None else "(no response)"

        except Exception as exc:
            logger.error(
                "[BaseChannel] Engine error | session=%s error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            return f"An error occurred while processing your request. (session: {session_id})"

    async def _send_chunked(
        self, chat_id: str, text: str, reply_to: str = ""
    ) -> None:
        """
        Split long text into platform-safe chunks and send sequentially.
        Only the first chunk uses reply_to; subsequent chunks are standalone.
        """
        if not text:
            return

        max_len = self.MAX_MESSAGE_LEN
        chunks = [text[i : i + max_len] for i in range(0, len(text), max_len)]

        for idx, chunk in enumerate(chunks):
            await self.send_message(
                chat_id,
                chunk,
                reply_to=reply_to if idx == 0 else "",
            )
