"""
ironcore/channels/telegram_bot.py — Telegram Bot connector.

Requires: python-telegram-bot>=20.0
Install:  pip install "python-telegram-bot>=20.0"

Features:
  - Text message → IronCore engine → streamed reply (edit-in-place)
  - Document/image upload → VLM pipeline
  - Commands: /start, /help, /clear, /model, /stats
  - Allowed-user allowlist (empty = allow all)
  - Long responses chunked at Telegram 4096-char limit
  - Streaming simulation: send "..." → edit with final response
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from ironcore.channels.base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)

# Telegram hard limit per message
_TELEGRAM_MAX_LEN = 4096

# ── Optional dependency guard ─────────────────────────────────────────────────
try:
    from telegram import Bot, Document, Message, PhotoSize, Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False
    # Provide typed stubs so type checkers don't break on missing import
    Update = Any              # type: ignore[assignment,misc]
    ContextTypes = Any        # type: ignore[assignment,misc]
    Application = Any         # type: ignore[assignment,misc]


def _require_telegram() -> None:
    if not _TELEGRAM_AVAILABLE:
        raise ImportError(
            "python-telegram-bot is not installed. "
            'Run: pip install "python-telegram-bot>=20.0"'
        )


# ── Commands ──────────────────────────────────────────────────────────────────

HELP_TEXT = """\
🤖 *IronCore AI Assistant*

Commands:
  /start  — Welcome message
  /help   — Show this help
  /clear  — Clear conversation history
  /model  — Show active LLM model
  /stats  — Show cost & usage metrics

Send any text message to chat with the AI.
Upload a document or image to process with vision.
"""

WELCOME_TEXT = """\
👋 Welcome to *IronCore AI*!

I'm your secure, privacy-first AI assistant.
Type any message to get started, or /help for commands.
"""


class TelegramChannel(BaseChannel):
    """
    Telegram Bot connector backed by python-telegram-bot v20+ (async native).

    Usage:
        channel = TelegramChannel(bot_token="...", allowed_user_ids=[12345])
        await channel.start()          # begins polling
        await channel.stop()           # graceful shutdown
    """

    MAX_MESSAGE_LEN = _TELEGRAM_MAX_LEN

    def __init__(
        self,
        bot_token: str,
        allowed_user_ids: Optional[List[int]] = None,
        engine: Any = None,
    ) -> None:
        _require_telegram()

        if not bot_token:
            raise ValueError("Telegram bot_token cannot be empty.")

        self._token = bot_token
        self._allowed_user_ids: List[int] = allowed_user_ids or []
        self._engine = engine
        self._app: Optional[Application] = None  # type: ignore[type-arg]

    # ── BaseChannel interface ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Build the Application, register handlers, and begin long-polling."""
        self._app = (
            Application.builder()
            .token(self._token)
            .build()
        )

        # Commands
        self._app.add_handler(CommandHandler("start",  self._cmd_start))
        self._app.add_handler(CommandHandler("help",   self._cmd_help))
        self._app.add_handler(CommandHandler("clear",  self._cmd_clear))
        self._app.add_handler(CommandHandler("model",  self._cmd_model))
        self._app.add_handler(CommandHandler("stats",  self._cmd_stats))

        # Text messages (non-command)
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        # Documents and photos
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info("[Telegram] Starting bot (polling)...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("[Telegram] Bot started and polling.")

    async def stop(self) -> None:
        """Gracefully stop polling and shut down."""
        if self._app is None:
            return
        logger.info("[Telegram] Stopping bot...")
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        self._app = None
        logger.info("[Telegram] Bot stopped.")

    async def send_message(
        self, chat_id: str, text: str, reply_to: str = ""
    ) -> str:
        """Send a new message. Returns the message_id string."""
        if self._app is None:
            raise RuntimeError("TelegramChannel not started. Call start() first.")
        kwargs: Dict[str, Any] = {
            "chat_id": int(chat_id),
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_to:
            try:
                kwargs["reply_to_message_id"] = int(reply_to)
            except ValueError:
                pass  # ignore non-integer reply_to values

        sent: Message = await self._app.bot.send_message(**kwargs)
        return str(sent.message_id)

    async def edit_message(
        self, chat_id: str, message_id: str, new_text: str
    ) -> None:
        """Edit a previously sent message (streaming simulation)."""
        if self._app is None:
            raise RuntimeError("TelegramChannel not started.")
        try:
            await self._app.bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=new_text,
                parse_mode="Markdown",
            )
        except Exception as exc:
            # Message may have been deleted or too old — not a critical error
            logger.warning("[Telegram] edit_message failed: %s", exc)

    async def send_typing(self, chat_id: str) -> None:
        """Send ChatAction.TYPING indicator."""
        if self._app is None:
            return
        try:
            await self._app.bot.send_chat_action(
                chat_id=int(chat_id), action="typing"
            )
        except Exception as exc:
            logger.debug("[Telegram] send_typing failed: %s", exc)

    # ── Message handlers ──────────────────────────────────────────────────────

    def _is_user_allowed(self, user_id: int) -> bool:
        """Return True if allowlist is empty (allow all) or user is in list."""
        return not self._allowed_user_ids or user_id in self._allowed_user_ids

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle plain text messages — route to engine with streaming simulation."""
        if update.effective_user is None or update.message is None:
            return

        user_id = update.effective_user.id
        if not self._is_user_allowed(user_id):
            logger.warning("[Telegram] Blocked unauthorised user_id=%s", user_id)
            return

        chat_id = str(update.effective_chat.id)
        text = update.message.text or ""
        message_id = str(update.message.message_id)

        # Streaming simulation: send placeholder, then edit with real response
        placeholder_id = await self.send_message(chat_id, "⏳ _Processing..._")

        msg = ChannelMessage(
            channel="telegram",
            user_id=str(user_id),
            chat_id=chat_id,
            text=text,
            message_id=message_id,
        )

        # Get response via engine
        session_id = f"telegram:{user_id}"
        response = await self._dispatch_to_engine(self._engine, msg, session_id)

        # Edit placeholder with actual response (first chunk)
        first_chunk = response[: _TELEGRAM_MAX_LEN]
        await self.edit_message(chat_id, placeholder_id, first_chunk)

        # Send remaining chunks as new messages
        if len(response) > _TELEGRAM_MAX_LEN:
            await self._send_chunked(
                chat_id, response[_TELEGRAM_MAX_LEN:], reply_to=""
            )

    async def _handle_document(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle uploaded documents — download and process via VLM if applicable."""
        if update.effective_user is None or update.message is None:
            return
        if not self._is_user_allowed(update.effective_user.id):
            return

        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)
        doc: Document = update.message.document

        # Get file URL for the document
        tg_file = await context.bot.get_file(doc.file_id)
        file_url = tg_file.file_path or ""

        msg = ChannelMessage(
            channel="telegram",
            user_id=user_id,
            chat_id=chat_id,
            text=update.message.caption or f"[Document: {doc.file_name}]",
            file_url=file_url,
            file_type="document",
            message_id=str(update.message.message_id),
        )

        await self.process_incoming(msg, self._engine)

    async def _handle_photo(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle uploaded photos — route to VLM pipeline."""
        if update.effective_user is None or update.message is None:
            return
        if not self._is_user_allowed(update.effective_user.id):
            return

        chat_id = str(update.effective_chat.id)
        user_id = str(update.effective_user.id)

        # Use the highest-resolution photo variant
        photos: List[PhotoSize] = update.message.photo
        best_photo = photos[-1] if photos else None
        file_url = ""
        if best_photo:
            tg_file = await context.bot.get_file(best_photo.file_id)
            file_url = tg_file.file_path or ""

        msg = ChannelMessage(
            channel="telegram",
            user_id=user_id,
            chat_id=chat_id,
            text=update.message.caption or "[Image]",
            file_url=file_url,
            file_type="image",
            message_id=str(update.message.message_id),
        )

        await self.process_incoming(msg, self._engine)

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _handle_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, command: str
    ) -> None:
        """Dispatch /command to the appropriate method."""
        handlers = {
            "start": self._cmd_start,
            "help": self._cmd_help,
            "clear": self._cmd_clear,
            "model": self._cmd_model,
            "stats": self._cmd_stats,
        }
        handler_fn = handlers.get(command)
        if handler_fn:
            await handler_fn(update, context)

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message:
            await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message:
            await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

    async def _cmd_clear(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message:
            user_id = str(update.effective_user.id) if update.effective_user else "unknown"
            session_id = f"telegram:{user_id}"
            # Signal engine to clear session if supported
            if self._engine and hasattr(self._engine, "clear_session"):
                await self._engine.clear_session(session_id)
            await update.message.reply_text(
                "🗑 Conversation history cleared.", parse_mode="Markdown"
            )

    async def _cmd_model(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message:
            model_name = os.getenv("IRONCORE_DEFAULT_MODEL", "Not configured")
            await update.message.reply_text(
                f"🤖 Active model: `{model_name}`", parse_mode="Markdown"
            )

    async def _cmd_stats(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if update.message:
            stats_text = "📊 *IronCore Stats*\n_Stats endpoint not yet connected._"
            if self._engine and hasattr(self._engine, "get_stats"):
                try:
                    stats = await self._engine.get_stats()
                    stats_text = f"📊 *IronCore Stats*\n```\n{stats}\n```"
                except Exception:
                    pass
            await update.message.reply_text(stats_text, parse_mode="Markdown")

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, engine: Any = None) -> "TelegramChannel":
        """
        Build a TelegramChannel from environment variables.

        Required env vars:
            TELEGRAM_BOT_TOKEN

        Optional env vars:
            TELEGRAM_ALLOWED_USER_IDS  — comma-separated integer IDs
        """
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN environment variable is not set. "
                "Get a token from @BotFather on Telegram."
            )

        raw_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
        allowed: List[int] = []
        if raw_ids:
            for part in raw_ids.split(","):
                part = part.strip()
                if part.isdigit():
                    allowed.append(int(part))

        return cls(bot_token=token, allowed_user_ids=allowed, engine=engine)
