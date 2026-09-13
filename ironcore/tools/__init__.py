"""
IronCore: Built-in Tools
========================
Production-grade tool implementations that ship with IronCore.
Each tool follows the @skill decorator pattern for automatic discovery.
"""

from ironcore.tools.web_search import web_search
from ironcore.tools.web_fetch import web_fetch
from ironcore.tools.run_shell import run_shell
from ironcore.tools.file_ops import file_read, file_write, file_list
from ironcore.tools.youtube_download import youtube_download
from ironcore.tools.tts_generate import tts_generate
from ironcore.tools.media_transcribe import media_transcribe
from ironcore.tools.image_generate import image_generate
from ironcore.tools.video_render import video_render
from ironcore.tools.ai_video_generate import ai_video_generate
from ironcore.tools.weather_fetch import weather_fetch
from ironcore.tools.github_search import github_search
from ironcore.tools.news_fetch import news_fetch
from ironcore.tools.crypto_price import crypto_price
from ironcore.tools.wikipedia_search import wikipedia_search
from ironcore.tools.currency_convert import currency_convert
from ironcore.tools.ip_geolocate import ip_geolocate
from ironcore.tools.browser_automate import browser_automate

ALL_TOOL_MODULES = [
    "ironcore.tools.web_search",
    "ironcore.tools.web_fetch",
    "ironcore.tools.run_shell",
    "ironcore.tools.file_ops",
    "ironcore.tools.youtube_download",
    "ironcore.tools.tts_generate",
    "ironcore.tools.media_transcribe",
    "ironcore.tools.image_generate",
    "ironcore.tools.video_render",
    "ironcore.tools.ai_video_generate",
    "ironcore.tools.weather_fetch",
    "ironcore.tools.github_search",
    "ironcore.tools.news_fetch",
    "ironcore.tools.crypto_price",
    "ironcore.tools.wikipedia_search",
    "ironcore.tools.currency_convert",
    "ironcore.tools.ip_geolocate",
    "ironcore.tools.browser_automate",
]

__all__ = [
    "web_search",
    "web_fetch",
    "run_shell",
    "file_read",
    "file_write",
    "file_list",
    "youtube_download",
    "tts_generate",
    "media_transcribe",
    "image_generate",
    "video_render",
    "ai_video_generate",
    "weather_fetch",
    "github_search",
    "news_fetch",
    "crypto_price",
    "wikipedia_search",
    "currency_convert",
    "ip_geolocate",
    "browser_automate",
    "ALL_TOOL_MODULES",
]
