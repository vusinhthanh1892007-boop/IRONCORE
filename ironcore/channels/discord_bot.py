"""
ironcore/channels/discord_bot.py — Discord Bot connector.

Requires: discord.py>=2.0
Install:  pip install "discord.py>=2.0"

Features:
  - Text message (mention or DM) → IronCore engine → reply
  - File attachment → file_url forwarded to VLM pipeline
  - Prefix commands: !ask, !clear, !stats, !help (in DMs or mention)
  - Allowed-guild allowlist (empty = allow all guilds)
  - Long responses chunked at Discord 2000-char limit
  - Streaming simulation: send placeholder → edit with response
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from ironcore.channels.base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)

# Discord hard limit per message
_DISCORD_MAX_LEN = 2000

# ── Optional dependency guard ─────────────────────────────────────────────────
try:
    import discord
    from discord import Client, Intents, Message as DiscordMessage
    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False
    discord = None      # type: ignore[assignment]
    Client = Any        # type: ignore[assignment,misc]
    Intents = Any       # type: ignore[assignment,misc]
    DiscordMessage = Any  # type: ignore[assignment,misc]


def _require_discord() -> None:
    if not _DISCORD_AVAILABLE:
        raise ImportError(
            "discord.py is not installed. "
            'Run: pip install "discord.py>=2.0"'
        )


# ── Commands ──────────────────────────────────────────────────────────────────

HELP_TEXT = """\
**IronCore AI Assistant**

Commands (prefix with `!`):
  `!ask <question>` — Ask the AI (same as mentioning the bot)
  `!clear` — Clear your conversation history
  `!model` — Show active LLM model
  `!stats` — Show cost & usage metrics
  `!help`  — Show this help

You can also mention the bot or DM it directly.
"""

# Command prefix for Discord text commands
_CMD_PREFIX = "!"


class DiscordChannel(BaseChannel):
    """
    Discord Bot connector backed by discord.py v2+ (async native).

    The bot listens for:
      - Direct messages (DMs)
      - Messages that @mention the bot
      - Messages prefixed with "!" in allowed guilds

    Usage:
        channel = DiscordChannel(bot_token="...", allowed_guild_ids=[123456])
        await channel.start()     # connects to Discord gateway
        await channel.stop()      # graceful disconnect
    """

    MAX_MESSAGE_LEN = _DISCORD_MAX_LEN

    def __init__(
        self,
        bot_token: str,
        allowed_guild_ids: Optional[List[int]] = None,
        engine: Any = None,
    ) -> None:
        _require_discord()

        if not bot_token:
            raise ValueError("Discord bot_token cannot be empty.")

        self._token = bot_token
        self._allowed_guild_ids: List[int] = allowed_guild_ids or []
        self._engine = engine
        self._client: Optional[DiscordChannel._IronCoreClient] = None  # type: ignore[name-defined]
        self._start_task: Optional[asyncio.Task[None]] = None

    # ── Inner Client class ────────────────────────────────────────────────────

    class _IronCoreClient(Client):  # type: ignore[misc]
        """Internal discord.Client subclass with IronCore handlers."""

        def __init__(
            self,
            outer: "DiscordChannel",
            **kwargs: Any,
        ) -> None:
            super().__init__(**kwargs)
            self._outer = outer

        async def on_ready(self) -> None:
            logger.info(
                "[Discord] Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?"
            )

        async def on_message(self, message: DiscordMessage) -> None:
            # Ignore messages from the bot itself
            if message.author == self.user:
                return

            outer = self._outer

            # Guild allowlist check
            guild_id = message.guild.id if message.guild else None
            if outer._allowed_guild_ids and guild_id not in outer._allowed_guild_ids:
                if message.guild is not None:
                    # Not in allowlist AND not a DM — skip
                    return

            is_dm = message.guild is None
            is_mention = self.user is not None and self.user.mentioned_in(message)
            is_command = message.content.startswith(_CMD_PREFIX)

            if not (is_dm or is_mention or is_command):
                return  # Not addressed to bot

            await outer._route_message(message)

    # ── BaseChannel interface ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Create the discord Client, connect to gateway, start event loop."""
        intents = Intents.default()
        intents.message_content = True  # Required for reading message text in v2

        self._client = DiscordChannel._IronCoreClient(
            outer=self,
            intents=intents,
        )

        logger.info("[Discord] Connecting to gateway...")
        # Run the client in a background task (client.start() blocks)
        self._start_task = asyncio.create_task(
            self._client.start(self._token),
            name="discord-client",
        )
        # Give the client a moment to connect before returning
        await asyncio.sleep(0.5)
        logger.info("[Discord] Bot started.")

    async def stop(self) -> None:
        """Gracefully close the Discord gateway connection."""
        if self._client is not None:
            logger.info("[Discord] Closing gateway connection...")
            await self._client.close()
            self._client = None

        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()
            try:
                await self._start_task
            except (asyncio.CancelledError, Exception):
                pass
            self._start_task = None

        logger.info("[Discord] Bot stopped.")

    async def send_message(
        self, chat_id: str, text: str, reply_to: str = ""
    ) -> str:
        """
        Send a message to a Discord channel or DM.
        chat_id should be the channel/DM channel_id (int as string).
        Returns message_id as string.
        """
        if self._client is None:
            raise RuntimeError("DiscordChannel not started. Call start() first.")

        try:
            channel_id = int(chat_id)
            channel = self._client.get_channel(channel_id)  # type: ignore[attr-defined]
            if channel is None:
                channel = await self._client.fetch_channel(channel_id)  # type: ignore[attr-defined]

            sent = await channel.send(text)
            return str(sent.id)
        except Exception as exc:
            logger.error("[Discord] send_message failed: %s", exc)
            raise

    async def edit_message(
        self, chat_id: str, message_id: str, new_text: str
    ) -> None:
        """Edit a previously sent message (streaming simulation)."""
        if self._client is None:
            raise RuntimeError("DiscordChannel not started.")
        try:
            channel_id = int(chat_id)
            channel = self._client.get_channel(channel_id)  # type: ignore[attr-defined]
            if channel is None:
                channel = await self._client.fetch_channel(channel_id)  # type: ignore[attr-defined]

            msg = await channel.fetch_message(int(message_id))
            await msg.edit(content=new_text)
        except Exception as exc:
            logger.warning("[Discord] edit_message failed: %s", exc)

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator (triggers the "Bot is typing..." indicator)."""
        if self._client is None:
            return
        try:
            channel_id = int(chat_id)
            channel = self._client.get_channel(channel_id)  # type: ignore[attr-defined]
            if channel is None:
                channel = await self._client.fetch_channel(channel_id)  # type: ignore[attr-defined]
            async with channel.typing():
                await asyncio.sleep(0)   # Trigger typing without blocking
        except Exception as exc:
            logger.debug("[Discord] send_typing failed: %s", exc)

    # ── Message routing ───────────────────────────────────────────────────────

    async def _route_message(self, message: DiscordMessage) -> None:
        """Decide whether to route as command or plain message."""
        content = message.content.strip()

        # Strip bot mention from the content
        if self._client and self._client.user:
            mention_str = f"<@{self._client.user.id}>"
            mention_nick = f"<@!{self._client.user.id}>"
            content = content.replace(mention_str, "").replace(mention_nick, "").strip()

        chat_id = str(message.channel.id)
        user_id = str(message.author.id)
        message_id = str(message.id)

        # Check for command prefix
        if content.startswith(_CMD_PREFIX):
            await self._handle_command(message, content[len(_CMD_PREFIX):].strip())
            return

        # Handle file attachments
        file_url: Optional[str] = None
        file_type: Optional[str] = None
        if message.attachments:
            attachment = message.attachments[0]
            file_url = attachment.url
            file_type = (
                "image"
                if attachment.content_type and attachment.content_type.startswith("image/")
                else "document"
            )

        msg = ChannelMessage(
            channel="discord",
            user_id=user_id,
            chat_id=chat_id,
            text=content or ("[Attachment]" if file_url else ""),
            file_url=file_url,
            file_type=file_type,
            message_id=message_id,
        )

        # Streaming simulation: send placeholder → edit with response
        placeholder_id = await self.send_message(chat_id, "⏳ Processing...")
        session_id = f"discord:{user_id}"
        response = await self._dispatch_to_engine(self._engine, msg, session_id)

        first_chunk = response[:_DISCORD_MAX_LEN]
        await self.edit_message(chat_id, placeholder_id, first_chunk)

        if len(response) > _DISCORD_MAX_LEN:
            await self._send_chunked(chat_id, response[_DISCORD_MAX_LEN:], reply_to="")

    async def _handle_command(self, message: DiscordMessage, raw: str) -> None:
        """
        Parse and dispatch !commands.
        raw = command name + args with _CMD_PREFIX stripped.
        """
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        chat_id = str(message.channel.id)
        user_id = str(message.author.id)

        if cmd == "help":
            await self.send_message(chat_id, HELP_TEXT)

        elif cmd in ("ask",) and args:
            msg = ChannelMessage(
                channel="discord",
                user_id=user_id,
                chat_id=chat_id,
                text=args,
                message_id=str(message.id),
            )
            await self.process_incoming(msg, self._engine)

        elif cmd == "clear":
            session_id = f"discord:{user_id}"
            if self._engine and hasattr(self._engine, "clear_session"):
                await self._engine.clear_session(session_id)
            await self.send_message(chat_id, "🗑 Conversation history cleared.")

        elif cmd == "model":
            model_name = os.getenv("IRONCORE_DEFAULT_MODEL", "Not configured")
            await self.send_message(chat_id, f"🤖 Active model: `{model_name}`")

        elif cmd == "stats":
            stats_text = "📊 Stats endpoint not yet connected."
            if self._engine and hasattr(self._engine, "get_stats"):
                try:
                    stats = await self._engine.get_stats()
                    stats_text = f"📊 **IronCore Stats**\n```\n{stats}\n```"
                except Exception:
                    pass
            await self.send_message(chat_id, stats_text)

        else:
            await self.send_message(
                chat_id,
                f"Unknown command `!{cmd}`. Type `!help` for available commands.",
            )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, engine: Any = None) -> "DiscordChannel":
        """
        Build a DiscordChannel from environment variables.

        Required env vars:
            DISCORD_BOT_TOKEN

        Optional env vars:
            DISCORD_ALLOWED_GUILDS  — comma-separated guild/server IDs
        """
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "DISCORD_BOT_TOKEN environment variable is not set. "
                "Create a bot at https://discord.com/developers/applications"
            )

        raw_guilds = os.getenv("DISCORD_ALLOWED_GUILDS", "").strip()
        allowed_guilds: List[int] = []
        if raw_guilds:
            for part in raw_guilds.split(","):
                part = part.strip()
                if part.isdigit():
                    allowed_guilds.append(int(part))

        return cls(bot_token=token, allowed_guild_ids=allowed_guilds, engine=engine)
