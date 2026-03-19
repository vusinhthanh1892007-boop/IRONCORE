"""
ironcore/channels — Multi-platform channel connectors.

Available channels:
  - telegram_bot.TelegramChannel  (requires: python-telegram-bot>=20.0)
  - discord_bot.DiscordChannel    (requires: discord.py>=2.0)
  - manager.ChannelManager        (orchestrator for all channels)
"""

from ironcore.channels.base import BaseChannel, ChannelMessage
from ironcore.channels.manager import ChannelManager

__all__ = [
    "BaseChannel",
    "ChannelMessage",
    "ChannelManager",
]
