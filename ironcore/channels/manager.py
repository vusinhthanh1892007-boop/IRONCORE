"""
ironcore/channels/manager.py — ChannelManager orchestrator.

Manages multiple channel connectors (Telegram, Discord) as a unified group:
  - start_all / stop_all with independent error handling per channel
  - broadcast: send proactive messages to all active channels
  - get_active_channels: list names of running connectors
  - from_env: factory to build all enabled channels from environment variables
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from ironcore.channels.base import BaseChannel

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Orchestrator for all IronCore channel connectors.

    Channels are registered by name (e.g. "telegram", "discord").
    start_all() starts each channel independently — one failing does not
    prevent others from starting.
    broadcast() sends a proactive message to every active channel's registered
    notification chat IDs.

    Usage:
        manager = ChannelManager()
        manager.register("telegram", telegram_channel)
        manager.register("discord", discord_channel)
        await manager.start_all()
        await manager.broadcast("IronCore started successfully.")
        await manager.stop_all()
    """

    def __init__(self) -> None:
        self._channels: Dict[str, BaseChannel] = {}
        self._active: Dict[str, bool] = {}
        # notification_chat_ids: {channel_name: [chat_id, ...]}
        # Used by broadcast() to know where to send proactive messages.
        self._notification_chats: Dict[str, List[str]] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        channel: BaseChannel,
        notification_chat_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Register a channel under a given name.

        Args:
            name: Unique identifier (e.g. "telegram", "discord").
            channel: BaseChannel instance to manage.
            notification_chat_ids: Chat IDs to receive broadcast() messages.
        """
        self._channels[name] = channel
        self._active[name] = False
        self._notification_chats[name] = notification_chat_ids or []
        logger.info("[ChannelManager] Registered channel: %s", name)

    def unregister(self, name: str) -> None:
        """Remove a channel from management (must be stopped first)."""
        self._channels.pop(name, None)
        self._active.pop(name, None)
        self._notification_chats.pop(name, None)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """
        Start all registered channels concurrently.
        Individual channel failures are logged but do NOT propagate — other
        channels continue starting normally.
        """
        if not self._channels:
            logger.warning("[ChannelManager] No channels registered — nothing to start.")
            return

        tasks = {
            name: asyncio.create_task(
                self._start_one(name, channel),
                name=f"channel-start-{name}",
            )
            for name, channel in self._channels.items()
        }
        await asyncio.gather(*tasks.values(), return_exceptions=True)

        active = [n for n, ok in self._active.items() if ok]
        failed = [n for n, ok in self._active.items() if not ok]

        if active:
            logger.info("[ChannelManager] Active channels: %s", active)
        if failed:
            logger.warning("[ChannelManager] Failed to start: %s", failed)

    async def stop_all(self) -> None:
        """
        Stop all active channels concurrently.
        Individual failures are logged but do not block other channels.
        """
        if not self._channels:
            return

        tasks = {
            name: asyncio.create_task(
                self._stop_one(name, channel),
                name=f"channel-stop-{name}",
            )
            for name, channel in self._channels.items()
        }
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        logger.info("[ChannelManager] All channels stopped.")

    async def _start_one(self, name: str, channel: BaseChannel) -> None:
        try:
            await channel.start()
            self._active[name] = True
            logger.info("[ChannelManager] Started: %s", name)
        except Exception as exc:
            self._active[name] = False
            logger.error("[ChannelManager] Failed to start %s: %s", name, exc, exc_info=True)

    async def _stop_one(self, name: str, channel: BaseChannel) -> None:
        try:
            await channel.stop()
            self._active[name] = False
            logger.info("[ChannelManager] Stopped: %s", name)
        except Exception as exc:
            logger.error("[ChannelManager] Error stopping %s: %s", name, exc, exc_info=True)

    # ── Status ────────────────────────────────────────────────────────────────

    def get_active_channels(self) -> List[str]:
        """Return names of channels that successfully started."""
        return [name for name, active in self._active.items() if active]

    def get_all_channels(self) -> List[str]:
        """Return names of all registered channels."""
        return list(self._channels.keys())

    def is_active(self, name: str) -> bool:
        """True if the named channel is currently running."""
        return self._active.get(name, False)

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast(
        self,
        message: str,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """
        Send a proactive message to all notification chat IDs on the specified
        channels (or all active channels if channels=None).

        Returns:
            Dict mapping channel_name → list of chat_ids successfully sent to.
        """
        target_names = channels if channels is not None else self.get_active_channels()
        results: Dict[str, List[str]] = {}

        for name in target_names:
            channel = self._channels.get(name)
            if channel is None:
                logger.warning("[ChannelManager] broadcast: channel %r not registered.", name)
                continue
            if not self._active.get(name):
                logger.debug("[ChannelManager] broadcast: channel %r not active, skipping.", name)
                continue

            chat_ids = self._notification_chats.get(name, [])
            if not chat_ids:
                logger.debug(
                    "[ChannelManager] broadcast: no notification chats for %r.", name
                )
                continue

            sent_to: List[str] = []
            for chat_id in chat_ids:
                try:
                    await channel.send_message(chat_id, message)
                    sent_to.append(chat_id)
                except Exception as exc:
                    logger.error(
                        "[ChannelManager] broadcast failed on %s chat=%s: %s",
                        name, chat_id, exc,
                    )

            results[name] = sent_to

        return results

    # ── Factory from env ──────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, engine: Any = None) -> "ChannelManager":
        """
        Build a ChannelManager from environment variables.

        IRONCORE_CHANNELS_ENABLED — comma-separated list of channels to enable.
            e.g. "telegram,discord"  (default: "" — no channels)

        Per-channel env vars:
            Telegram:
                TELEGRAM_BOT_TOKEN           (required)
                TELEGRAM_ALLOWED_USER_IDS    (optional, comma-sep ints)
                TELEGRAM_NOTIFICATION_CHATS  (optional, comma-sep chat IDs)

            Discord:
                DISCORD_BOT_TOKEN            (required)
                DISCORD_ALLOWED_GUILDS       (optional, comma-sep ints)
                DISCORD_NOTIFICATION_CHATS   (optional, comma-sep channel IDs)
        """
        manager = cls()

        enabled_raw = os.getenv("IRONCORE_CHANNELS_ENABLED", "").strip()
        if not enabled_raw:
            logger.info("[ChannelManager] IRONCORE_CHANNELS_ENABLED not set — no channels loaded.")
            return manager

        enabled = [c.strip().lower() for c in enabled_raw.split(",") if c.strip()]

        for channel_name in enabled:
            try:
                if channel_name == "telegram":
                    from ironcore.channels.telegram_bot import TelegramChannel
                    channel = TelegramChannel.from_env(engine=engine)
                    notif_raw = os.getenv("TELEGRAM_NOTIFICATION_CHATS", "")
                    notif_chats = [c.strip() for c in notif_raw.split(",") if c.strip()]
                    manager.register("telegram", channel, notification_chat_ids=notif_chats)

                elif channel_name == "discord":
                    from ironcore.channels.discord_bot import DiscordChannel
                    channel = DiscordChannel.from_env(engine=engine)
                    notif_raw = os.getenv("DISCORD_NOTIFICATION_CHATS", "")
                    notif_chats = [c.strip() for c in notif_raw.split(",") if c.strip()]
                    manager.register("discord", channel, notification_chat_ids=notif_chats)

                else:
                    logger.warning(
                        "[ChannelManager] Unknown channel type %r — skipping.", channel_name
                    )

            except (ImportError, ValueError) as exc:
                logger.error(
                    "[ChannelManager] Cannot load channel %r: %s", channel_name, exc
                )

        return manager
