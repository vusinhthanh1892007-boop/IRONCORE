"""
tests/test_phase5_architect_channels.py — Phase 5: Channel Connectors

Tests cover:
  - ChannelMessage model validation
  - BaseChannel._send_chunked splits text correctly
  - BaseChannel.process_incoming routes to engine and returns response
  - BaseChannel._dispatch_to_engine: process_message, callable, None engine
  - Session ID format: "{platform}:{user_id}"
  - TelegramChannel (fully mocked) — no real token needed
    * Construction validation
    * send_message / edit_message delegation to bot
    * _handle_message → placeholder sent → edited with response
    * _cmd_clear calls engine.clear_session
    * Unauthorised user blocked
    * from_env factory
  - DiscordChannel (fully mocked) — no real token needed
    * Construction validation
    * _route_message → text message → engine dispatched
    * _handle_command: !help, !clear, !ask, !model, !stats, unknown
    * Chunking at 2000-char limit
    * from_env factory
  - ChannelManager
    * register / unregister
    * start_all: success + partial failure
    * stop_all
    * get_active_channels
    * broadcast to notification chats
    * from_env with IRONCORE_CHANNELS_ENABLED
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_engine(response: str = "Mock engine response") -> AsyncMock:
    """Return a mock engine with async process_message."""
    engine = AsyncMock()
    engine.process_message = AsyncMock(return_value=response)
    engine.clear_session = AsyncMock()
    engine.get_stats = AsyncMock(return_value="requests=42 tokens=1337")
    return engine


# ── Inject stub telegram module so TelegramChannel imports without the real lib ──

def _build_telegram_stub() -> types.ModuleType:
    """Build a minimal fake `telegram` package in sys.modules."""
    telegram_mod = types.ModuleType("telegram")
    telegram_ext_mod = types.ModuleType("telegram.ext")

    # Data classes we reference
    telegram_mod.Bot = MagicMock
    telegram_mod.Update = MagicMock
    telegram_mod.Document = MagicMock
    telegram_mod.Message = MagicMock
    telegram_mod.PhotoSize = MagicMock

    # Application builder pattern
    class FakeApplication:
        def __init__(self) -> None:
            self.bot = AsyncMock()
            self.bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
            self.bot.edit_message_text = AsyncMock()
            self.bot.send_chat_action = AsyncMock()
            self.updater = AsyncMock()
            self.updater.start_polling = AsyncMock()
            self.updater.stop = AsyncMock()
            self._handlers: List = []

        def add_handler(self, handler: Any) -> None:
            self._handlers.append(handler)

        async def initialize(self) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def shutdown(self) -> None:
            pass

    class FakeBuilder:
        def __init__(self) -> None:
            self._app = FakeApplication()

        def token(self, t: str) -> "FakeBuilder":
            self._app.bot._token = t
            return self

        def build(self) -> FakeApplication:
            return self._app

    class FakeApplicationClass:
        @staticmethod
        def builder() -> FakeBuilder:
            return FakeBuilder()

    telegram_ext_mod.Application = FakeApplicationClass
    telegram_ext_mod.CommandHandler = MagicMock(return_value=MagicMock())
    telegram_ext_mod.MessageHandler = MagicMock(return_value=MagicMock())
    telegram_ext_mod.ContextTypes = MagicMock()

    # filters namespace
    fake_filters = MagicMock()
    fake_filters.TEXT = MagicMock()
    fake_filters.COMMAND = MagicMock()
    fake_filters.Document = MagicMock()
    fake_filters.Document.ALL = MagicMock()
    fake_filters.PHOTO = MagicMock()
    telegram_ext_mod.filters = fake_filters

    sys.modules["telegram"] = telegram_mod
    sys.modules["telegram.ext"] = telegram_ext_mod
    # Patch the availability flag in the bot module if already loaded
    return telegram_mod


def _build_discord_stub() -> types.ModuleType:
    """Build a minimal fake `discord` package in sys.modules."""
    discord_mod = types.ModuleType("discord")

    class FakeIntents:
        message_content: bool = False

        @classmethod
        def default(cls) -> "FakeIntents":
            return cls()

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.user = MagicMock()
            self.user.id = 99999
            self.user.mentioned_in = MagicMock(return_value=False)
            self._start_called = False

        async def start(self, token: str) -> None:
            self._start_called = True

        async def close(self) -> None:
            pass

        def get_channel(self, channel_id: int) -> MagicMock:
            chan = AsyncMock()
            chan.send = AsyncMock(return_value=MagicMock(id=1001))
            chan.fetch_message = AsyncMock(return_value=AsyncMock(edit=AsyncMock()))
            chan.typing = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=None),
            ))
            return chan

        async def fetch_channel(self, channel_id: int) -> MagicMock:
            return self.get_channel(channel_id)

    discord_mod.Client = FakeClient
    discord_mod.Intents = FakeIntents
    discord_mod.Message = MagicMock

    sys.modules["discord"] = discord_mod
    return discord_mod


# Install stubs before any channel imports
_build_telegram_stub()
_build_discord_stub()

# Now import channels (they will use the stubs)
from ironcore.channels.base import BaseChannel, ChannelMessage  # noqa: E402
from ironcore.channels.manager import ChannelManager  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# ChannelMessage
# ══════════════════════════════════════════════════════════════════════════════

class TestChannelMessage:
    def test_minimal_fields(self) -> None:
        msg = ChannelMessage(channel="telegram", user_id="123", chat_id="456")
        assert msg.channel == "telegram"
        assert msg.user_id == "123"
        assert msg.chat_id == "456"
        assert msg.text is None
        assert msg.file_url is None

    def test_full_fields(self) -> None:
        msg = ChannelMessage(
            channel="discord",
            user_id="u1",
            chat_id="c1",
            text="hello",
            file_url="https://example.com/file.pdf",
            file_type="document",
            message_id="m1",
            thread_id="t1",
        )
        assert msg.file_type == "document"
        assert msg.thread_id == "t1"


# ══════════════════════════════════════════════════════════════════════════════
# BaseChannel (concrete stub for testing abstract methods)
# ══════════════════════════════════════════════════════════════════════════════

class StubChannel(BaseChannel):
    """Minimal concrete implementation for unit-testing BaseChannel logic."""

    MAX_MESSAGE_LEN = 20  # Small limit to test chunking easily

    def __init__(self) -> None:
        self.sent: List[Dict] = []
        self.edited: List[Dict] = []
        self.typing_sent: List[str] = []
        self._msg_counter = 0

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> str:
        self._msg_counter += 1
        msg_id = str(self._msg_counter)
        self.sent.append({"chat_id": chat_id, "text": text, "reply_to": reply_to, "id": msg_id})
        return msg_id

    async def edit_message(self, chat_id: str, message_id: str, new_text: str) -> None:
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "new_text": new_text})

    async def send_typing(self, chat_id: str) -> None:
        self.typing_sent.append(chat_id)


@pytest.mark.asyncio
class TestBaseChannelChunking:
    async def test_no_text_sends_nothing(self) -> None:
        ch = StubChannel()
        await ch._send_chunked("c1", "")
        assert ch.sent == []

    async def test_short_text_single_message(self) -> None:
        ch = StubChannel()
        await ch._send_chunked("c1", "hello")
        assert len(ch.sent) == 1
        assert ch.sent[0]["text"] == "hello"

    async def test_long_text_splits_into_chunks(self) -> None:
        ch = StubChannel()
        # MAX_MESSAGE_LEN = 20, text = 55 chars → 3 chunks
        text = "A" * 55
        await ch._send_chunked("c1", text)
        assert len(ch.sent) == 3
        assert len(ch.sent[0]["text"]) == 20
        assert len(ch.sent[1]["text"]) == 20
        assert len(ch.sent[2]["text"]) == 15

    async def test_reply_to_only_first_chunk(self) -> None:
        ch = StubChannel()
        text = "B" * 45  # 3 chunks of 20, 20, 5
        await ch._send_chunked("c1", text, reply_to="msg99")
        assert ch.sent[0]["reply_to"] == "msg99"
        assert ch.sent[1]["reply_to"] == ""
        assert ch.sent[2]["reply_to"] == ""

    async def test_chunk_content_no_data_loss(self) -> None:
        ch = StubChannel()
        text = "ABCDEFGHIJ" * 7  # 70 chars → 4 chunks (20,20,20,10)
        await ch._send_chunked("c1", text)
        reassembled = "".join(m["text"] for m in ch.sent)
        assert reassembled == text


@pytest.mark.asyncio
class TestBaseChannelDispatch:
    async def test_dispatch_with_process_message_engine(self) -> None:
        ch = StubChannel()
        engine = make_engine("Great response")
        msg = ChannelMessage(channel="telegram", user_id="u1", chat_id="c1", text="hello")
        result = await ch._dispatch_to_engine(engine, msg, "telegram:u1")
        assert result == "Great response"
        engine.process_message.assert_awaited_once_with("hello", "telegram:u1")

    async def test_dispatch_callable_engine(self) -> None:
        ch = StubChannel()
        async def callable_engine(text: str, session_id: str) -> str:
            return f"Callable got: {text}"

        msg = ChannelMessage(channel="telegram", user_id="u1", chat_id="c1", text="hi")
        result = await ch._dispatch_to_engine(callable_engine, msg, "telegram:u1")
        assert result == "Callable got: hi"

    async def test_dispatch_none_engine_returns_placeholder(self) -> None:
        ch = StubChannel()
        msg = ChannelMessage(channel="discord", user_id="u2", chat_id="c2", text="?")
        result = await ch._dispatch_to_engine(None, msg, "discord:u2")
        assert "not connected" in result.lower()

    async def test_dispatch_engine_exception_returns_error_message(self) -> None:
        ch = StubChannel()
        engine = AsyncMock()
        engine.process_message = AsyncMock(side_effect=RuntimeError("LLM down"))
        msg = ChannelMessage(channel="telegram", user_id="u1", chat_id="c1", text="test")
        result = await ch._dispatch_to_engine(engine, msg, "telegram:u1")
        assert "error" in result.lower()

    async def test_process_incoming_sends_typing_and_response(self) -> None:
        ch = StubChannel()
        engine = make_engine("Engine says hi")
        msg = ChannelMessage(channel="telegram", user_id="42", chat_id="c1", text="Hello AI")
        await ch.process_incoming(msg, engine)
        assert "c1" in ch.typing_sent
        assert any("Engine says hi" in s["text"] for s in ch.sent)

    async def test_session_id_format(self) -> None:
        """Session ID must be {channel}:{user_id}."""
        ch = StubChannel()
        captured_session: List[str] = []

        async def capturing_engine(text: str, session_id: str) -> str:
            captured_session.append(session_id)
            return "ok"

        msg = ChannelMessage(
            channel="telegram", user_id="99", chat_id="c1", text="test"
        )
        await ch.process_incoming(msg, capturing_engine)
        assert captured_session == ["telegram:99"]

    async def test_session_id_discord_format(self) -> None:
        ch = StubChannel()
        captured: List[str] = []

        async def cap_engine(text: str, session_id: str) -> str:
            captured.append(session_id)
            return "ok"

        msg = ChannelMessage(channel="discord", user_id="777", chat_id="c2", text="hi")
        await ch.process_incoming(msg, cap_engine)
        assert captured == ["discord:777"]


# ══════════════════════════════════════════════════════════════════════════════
# TelegramChannel
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestTelegramChannel:
    def _make_channel(
        self,
        token: str = "test:token",
        allowed: Optional[List[int]] = None,
        engine: Any = None,
    ):
        # Patch _TELEGRAM_AVAILABLE before import
        with patch("ironcore.channels.telegram_bot._TELEGRAM_AVAILABLE", True):
            from ironcore.channels.telegram_bot import TelegramChannel
            return TelegramChannel(
                bot_token=token,
                allowed_user_ids=allowed,
                engine=engine,
            )

    def test_empty_token_raises(self) -> None:
        with patch("ironcore.channels.telegram_bot._TELEGRAM_AVAILABLE", True):
            from ironcore.channels.telegram_bot import TelegramChannel
            with pytest.raises(ValueError, match="bot_token"):
                TelegramChannel(bot_token="")

    def test_unavailable_library_raises_import_error(self) -> None:
        with patch("ironcore.channels.telegram_bot._TELEGRAM_AVAILABLE", False):
            from ironcore.channels.telegram_bot import TelegramChannel
            with pytest.raises(ImportError, match="python-telegram-bot"):
                TelegramChannel(bot_token="abc")

    def test_is_user_allowed_empty_allowlist(self) -> None:
        ch = self._make_channel(allowed=[])
        assert ch._is_user_allowed(99999) is True

    def test_is_user_allowed_with_allowlist(self) -> None:
        ch = self._make_channel(allowed=[100, 200])
        assert ch._is_user_allowed(100) is True
        assert ch._is_user_allowed(300) is False

    async def test_send_message_delegates_to_bot(self) -> None:
        ch = self._make_channel()
        # Mock the internal _app with a fake bot
        fake_app = MagicMock()
        fake_sent = MagicMock(message_id=77)
        fake_app.bot.send_message = AsyncMock(return_value=fake_sent)
        ch._app = fake_app

        result = await ch.send_message("12345", "Hello!", reply_to="")
        fake_app.bot.send_message.assert_awaited_once()
        assert result == "77"

    async def test_send_message_with_reply_to(self) -> None:
        ch = self._make_channel()
        fake_app = MagicMock()
        fake_sent = MagicMock(message_id=88)
        fake_app.bot.send_message = AsyncMock(return_value=fake_sent)
        ch._app = fake_app

        await ch.send_message("111", "Reply text", reply_to="55")
        call_kwargs = fake_app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_to_message_id") == 55

    async def test_edit_message_delegates_to_bot(self) -> None:
        ch = self._make_channel()
        fake_app = MagicMock()
        fake_app.bot.edit_message_text = AsyncMock()
        ch._app = fake_app

        await ch.edit_message("111", "42", "Updated text")
        fake_app.bot.edit_message_text.assert_awaited_once_with(
            chat_id=111, message_id=42, text="Updated text", parse_mode="Markdown"
        )

    async def test_send_typing_delegates(self) -> None:
        ch = self._make_channel()
        fake_app = MagicMock()
        fake_app.bot.send_chat_action = AsyncMock()
        ch._app = fake_app

        await ch.send_typing("999")
        fake_app.bot.send_chat_action.assert_awaited_once()

    async def test_handle_message_sends_placeholder_and_edits(self) -> None:
        """Test streaming simulation: placeholder sent, then edited with response."""
        engine = make_engine("Final answer")
        ch = self._make_channel(engine=engine)

        # Track calls
        sent_messages: List[Dict] = []
        edited_messages: List[Dict] = []

        async def fake_send(chat_id: str, text: str, reply_to: str = "") -> str:
            sent_messages.append({"chat_id": chat_id, "text": text})
            return "placeholder_id"

        async def fake_edit(chat_id: str, message_id: str, new_text: str) -> None:
            edited_messages.append({"chat_id": chat_id, "msg_id": message_id, "text": new_text})

        ch.send_message = fake_send
        ch.edit_message = fake_edit
        ch.send_typing = AsyncMock()

        # Build a fake update
        fake_update = MagicMock()
        fake_update.effective_user.id = 123
        fake_update.effective_chat.id = 456
        fake_update.message.text = "Hello bot"
        fake_update.message.message_id = 10

        await ch._handle_message(fake_update, MagicMock())

        # Placeholder was sent first
        assert len(sent_messages) == 1
        assert "Processing" in sent_messages[0]["text"] or "⏳" in sent_messages[0]["text"]

        # Then edited with actual response
        assert len(edited_messages) == 1
        assert edited_messages[0]["text"] == "Final answer"

    async def test_handle_message_blocks_unauthorised_user(self) -> None:
        ch = self._make_channel(allowed=[999])
        ch.send_message = AsyncMock()
        ch.send_typing = AsyncMock()

        fake_update = MagicMock()
        fake_update.effective_user.id = 111  # Not in allow list
        fake_update.effective_chat.id = 456
        fake_update.message.text = "Access"
        fake_update.message.message_id = 1

        await ch._handle_message(fake_update, MagicMock())
        ch.send_message.assert_not_awaited()

    async def test_cmd_clear_calls_engine_clear_session(self) -> None:
        engine = make_engine()
        ch = self._make_channel(engine=engine)

        fake_update = MagicMock()
        fake_update.effective_user.id = 42
        fake_update.message.reply_text = AsyncMock()

        await ch._cmd_clear(fake_update, MagicMock())
        engine.clear_session.assert_awaited_once_with("telegram:42")

    async def test_from_env_missing_token_raises(self) -> None:
        with patch("ironcore.channels.telegram_bot._TELEGRAM_AVAILABLE", True):
            with patch.dict("os.environ", {}, clear=False):
                os_env = {"TELEGRAM_BOT_TOKEN": ""}
                with patch.dict("os.environ", os_env):
                    from ironcore.channels.telegram_bot import TelegramChannel
                    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
                        TelegramChannel.from_env()

    async def test_from_env_parses_allowed_user_ids(self) -> None:
        with patch("ironcore.channels.telegram_bot._TELEGRAM_AVAILABLE", True):
            with patch.dict("os.environ", {
                "TELEGRAM_BOT_TOKEN": "fake:token",
                "TELEGRAM_ALLOWED_USER_IDS": "111,222,333",
            }):
                from ironcore.channels.telegram_bot import TelegramChannel
                ch = TelegramChannel.from_env()
                assert ch._allowed_user_ids == [111, 222, 333]


# ══════════════════════════════════════════════════════════════════════════════
# DiscordChannel
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestDiscordChannel:
    def _make_channel(
        self,
        token: str = "discord_test_token",
        allowed_guilds: Optional[List[int]] = None,
        engine: Any = None,
    ):
        with patch("ironcore.channels.discord_bot._DISCORD_AVAILABLE", True):
            from ironcore.channels.discord_bot import DiscordChannel
            return DiscordChannel(
                bot_token=token,
                allowed_guild_ids=allowed_guilds,
                engine=engine,
            )

    def test_empty_token_raises(self) -> None:
        with patch("ironcore.channels.discord_bot._DISCORD_AVAILABLE", True):
            from ironcore.channels.discord_bot import DiscordChannel
            with pytest.raises(ValueError, match="bot_token"):
                DiscordChannel(bot_token="")

    def test_unavailable_library_raises(self) -> None:
        with patch("ironcore.channels.discord_bot._DISCORD_AVAILABLE", False):
            from ironcore.channels.discord_bot import DiscordChannel
            with pytest.raises(ImportError, match="discord.py"):
                DiscordChannel(bot_token="x")

    async def test_send_message_delegates_to_client(self) -> None:
        ch = self._make_channel()
        sent_msg = MagicMock(id=555)
        fake_channel = AsyncMock()
        fake_channel.send = AsyncMock(return_value=sent_msg)

        fake_client = MagicMock()
        fake_client.get_channel = MagicMock(return_value=fake_channel)
        ch._client = fake_client

        result = await ch.send_message("12345", "Hi Discord")
        assert result == "555"
        fake_channel.send.assert_awaited_once_with("Hi Discord")

    async def test_max_message_len_is_2000(self) -> None:
        ch = self._make_channel()
        assert ch.MAX_MESSAGE_LEN == 2000

    async def test_chunking_at_2000_chars(self) -> None:
        ch = self._make_channel()
        sent_texts: List[str] = []

        async def fake_send(chat_id: str, text: str, reply_to: str = "") -> str:
            sent_texts.append(text)
            return str(len(sent_texts))

        ch.send_message = fake_send
        text = "Z" * 4500  # 3 Discord chunks: 2000, 2000, 500
        await ch._send_chunked("c1", text)
        assert len(sent_texts) == 3
        assert len(sent_texts[0]) == 2000
        assert len(sent_texts[2]) == 500

    async def test_route_message_dispatches_to_engine(self) -> None:
        engine = make_engine("Discord engine reply")
        ch = self._make_channel(engine=engine)

        sent_messages: List[Dict] = []
        edited_messages: List[Dict] = []

        async def fake_send(chat_id: str, text: str, reply_to: str = "") -> str:
            sent_messages.append({"text": text})
            return "placeholder_id"

        async def fake_edit(chat_id: str, message_id: str, new_text: str) -> None:
            edited_messages.append({"text": new_text})

        ch.send_message = fake_send
        ch.edit_message = fake_edit
        ch.send_typing = AsyncMock()

        fake_message = MagicMock()
        fake_message.content = "Hello Discord"
        fake_message.author.id = 321
        fake_message.channel.id = 654
        fake_message.id = 11
        fake_message.guild = MagicMock()
        fake_message.attachments = []

        # Simulate bot user for mention stripping
        ch._client = MagicMock()
        ch._client.user.id = 99999
        ch._client.user.mentioned_in = MagicMock(return_value=False)

        await ch._route_message(fake_message)

        assert any("Processing" in m["text"] or "⏳" in m["text"] for m in sent_messages)
        assert any("Discord engine reply" in m["text"] for m in edited_messages)

    async def test_handle_command_help(self) -> None:
        ch = self._make_channel()
        sent: List[str] = []

        async def fake_send(chat_id: str, text: str, reply_to: str = "") -> str:
            sent.append(text)
            return "1"

        ch.send_message = fake_send

        fake_msg = MagicMock()
        fake_msg.channel.id = 111
        fake_msg.author.id = 1

        await ch._handle_command(fake_msg, "help")
        assert any("Commands" in t or "IronCore" in t for t in sent)

    async def test_handle_command_clear(self) -> None:
        engine = make_engine()
        ch = self._make_channel(engine=engine)
        ch.send_message = AsyncMock(return_value="1")

        fake_msg = MagicMock()
        fake_msg.channel.id = 111
        fake_msg.author.id = 777

        await ch._handle_command(fake_msg, "clear")
        engine.clear_session.assert_awaited_once_with("discord:777")

    async def test_handle_command_ask_dispatches(self) -> None:
        engine = make_engine("Ask answer")
        ch = self._make_channel(engine=engine)
        ch.send_message = AsyncMock(return_value="1")
        ch.send_typing = AsyncMock()

        fake_msg = MagicMock()
        fake_msg.channel.id = 111
        fake_msg.author.id = 42
        fake_msg.id = 5

        await ch._handle_command(fake_msg, "ask what is AI?")
        engine.process_message.assert_awaited_once()
        call_args = engine.process_message.call_args[0]
        assert call_args[0] == "what is AI?"

    async def test_handle_command_unknown(self) -> None:
        ch = self._make_channel()
        sent: List[str] = []

        async def fake_send(chat_id: str, text: str, reply_to: str = "") -> str:
            sent.append(text)
            return "1"

        ch.send_message = fake_send

        fake_msg = MagicMock()
        fake_msg.channel.id = 111
        fake_msg.author.id = 1

        await ch._handle_command(fake_msg, "unknown_cmd")
        assert any("Unknown command" in t for t in sent)

    async def test_from_env_missing_token_raises(self) -> None:
        with patch("ironcore.channels.discord_bot._DISCORD_AVAILABLE", True):
            with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": ""}):
                from ironcore.channels.discord_bot import DiscordChannel
                with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
                    DiscordChannel.from_env()

    async def test_from_env_parses_allowed_guilds(self) -> None:
        with patch("ironcore.channels.discord_bot._DISCORD_AVAILABLE", True):
            with patch.dict("os.environ", {
                "DISCORD_BOT_TOKEN": "faketoken",
                "DISCORD_ALLOWED_GUILDS": "111111,222222",
            }):
                from ironcore.channels.discord_bot import DiscordChannel
                ch = DiscordChannel.from_env()
                assert ch._allowed_guild_ids == [111111, 222222]


# ══════════════════════════════════════════════════════════════════════════════
# ChannelManager
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestChannelManager:
    def _make_stub(self, name: str = "stub") -> StubChannel:
        return StubChannel()

    def test_register_channel(self) -> None:
        manager = ChannelManager()
        ch = self._make_stub()
        manager.register("test", ch)
        assert "test" in manager.get_all_channels()

    def test_unregister_channel(self) -> None:
        manager = ChannelManager()
        ch = self._make_stub()
        manager.register("test", ch)
        manager.unregister("test")
        assert "test" not in manager.get_all_channels()

    async def test_start_all_marks_as_active(self) -> None:
        manager = ChannelManager()
        ch = StubChannel()
        manager.register("telegram", ch)
        await manager.start_all()
        assert "telegram" in manager.get_active_channels()

    async def test_start_all_partial_failure(self) -> None:
        """One failing channel should not prevent others from starting."""

        class BadChannel(StubChannel):
            async def start(self) -> None:
                raise RuntimeError("Intentional failure")

        manager = ChannelManager()
        good_ch = StubChannel()
        bad_ch = BadChannel()
        manager.register("good", good_ch)
        manager.register("bad", bad_ch)

        await manager.start_all()

        assert "good" in manager.get_active_channels()
        assert "bad" not in manager.get_active_channels()

    async def test_stop_all_marks_as_inactive(self) -> None:
        manager = ChannelManager()
        ch = StubChannel()
        manager.register("discord", ch)
        await manager.start_all()
        await manager.stop_all()
        assert "discord" not in manager.get_active_channels()

    async def test_is_active(self) -> None:
        manager = ChannelManager()
        ch = StubChannel()
        manager.register("mybot", ch)
        assert manager.is_active("mybot") is False
        await manager.start_all()
        assert manager.is_active("mybot") is True

    async def test_broadcast_sends_to_notification_chats(self) -> None:
        manager = ChannelManager()
        ch = StubChannel()
        manager.register("telegram", ch, notification_chat_ids=["chat1", "chat2"])
        await manager.start_all()

        result = await manager.broadcast("System alert!")

        assert "telegram" in result
        assert set(result["telegram"]) == {"chat1", "chat2"}
        assert len(ch.sent) == 2
        assert all(s["text"] == "System alert!" for s in ch.sent)

    async def test_broadcast_only_active_channels(self) -> None:
        manager = ChannelManager()
        ch = StubChannel()
        manager.register("inactive", ch, notification_chat_ids=["c1"])
        # Do NOT start — channel stays inactive

        result = await manager.broadcast("Hello")
        assert result == {}  # Nothing sent

    async def test_broadcast_specific_channels_only(self) -> None:
        manager = ChannelManager()
        tg = StubChannel()
        dc = StubChannel()
        manager.register("telegram", tg, notification_chat_ids=["tg1"])
        manager.register("discord", dc, notification_chat_ids=["dc1"])
        await manager.start_all()

        result = await manager.broadcast("Only Telegram", channels=["telegram"])
        assert "telegram" in result
        assert "discord" not in result
        assert len(tg.sent) == 1
        assert len(dc.sent) == 0

    async def test_start_all_empty_channels(self) -> None:
        """start_all with no channels should not raise."""
        manager = ChannelManager()
        await manager.start_all()  # Should not raise
        assert manager.get_active_channels() == []

    async def test_from_env_no_channels_enabled(self) -> None:
        with patch.dict("os.environ", {"IRONCORE_CHANNELS_ENABLED": ""}):
            manager = ChannelManager.from_env()
        assert manager.get_all_channels() == []

    async def test_from_env_unknown_channel_skipped(self) -> None:
        with patch.dict("os.environ", {"IRONCORE_CHANNELS_ENABLED": "slack"}):
            manager = ChannelManager.from_env()
        assert "slack" not in manager.get_all_channels()
