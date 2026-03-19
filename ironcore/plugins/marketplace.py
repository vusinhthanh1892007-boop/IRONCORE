"""
IronCore V2: Plugin Marketplace
==================================
Phase 1 — The Architect (Gemini 3.1)

PluginMarketplace đọc plugin index từ remote JSON endpoint,
cho phép search, list featured plugins, và install trực tiếp.

Mặc định index URL: IRONCORE_PLUGIN_MARKETPLACE_URL
Fallback khi offline: trả về empty list, không crash.

Author: The Architect (IronCore V2) — Gemini 3.1
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import asyncio

from .manifest import PluginManifest

logger = logging.getLogger(__name__)

_DEFAULT_MARKETPLACE_URL = "https://plugins.ironcore.dev/index.json"
_CACHE_TTL_SECONDS = 300   # Cache index 5 phút


class PluginMarketplace:
    """
    Client đọc plugin index từ remote marketplace.

    Caching: index được cache in-memory TTL 5 phút để tránh gọi liên tục.
    Offline-safe: mọi lỗi network đều bị catch và trả về empty/None.

    Usage:
        marketplace = PluginMarketplace()
        featured = await marketplace.get_featured()
        results = await marketplace.search("weather")
        info = await marketplace.get_plugin_info("weather-fetcher")
    """

    def __init__(
        self,
        marketplace_url: Optional[str] = None,
        timeout_seconds: int = 10,
    ) -> None:
        self._url = marketplace_url or os.getenv(
            "IRONCORE_PLUGIN_MARKETPLACE_URL",
            _DEFAULT_MARKETPLACE_URL,
        )
        self._timeout = timeout_seconds
        self._index_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_fetched_at: float = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def search(self, query: str) -> List[PluginManifest]:
        """
        Tìm kiếm plugin trong index theo query string.

        Tìm theo: id, name, description, tags.
        Không phân biệt hoa thường.

        Args:
            query: Từ khóa tìm kiếm

        Returns:
            Danh sách PluginManifest khớp (tối đa 20 kết quả).
        """
        index = await self._get_index()
        if not index:
            return []

        query_lower = query.strip().lower()
        results: List[PluginManifest] = []

        for entry in index:
            if self._matches(entry, query_lower):
                manifest = self._parse_entry(entry)
                if manifest:
                    results.append(manifest)
            if len(results) >= 20:
                break

        logger.info(
            "[Marketplace] search | query=%r results=%d",
            query,
            len(results),
        )
        return results

    async def get_featured(self) -> List[PluginManifest]:
        """
        Lấy danh sách plugins nổi bật (có field 'featured': true trong index).

        Returns:
            Danh sách PluginManifest có featured=true.
        """
        index = await self._get_index()
        if not index:
            return []

        featured: List[PluginManifest] = []
        for entry in index:
            if entry.get("featured", False):
                manifest = self._parse_entry(entry)
                if manifest:
                    featured.append(manifest)

        logger.info("[Marketplace] get_featured | count=%d", len(featured))
        return featured

    async def get_plugin_info(self, plugin_id: str) -> Optional[PluginManifest]:
        """
        Lấy thông tin chi tiết của một plugin theo ID từ marketplace.

        Args:
            plugin_id: Plugin ID cần tra cứu

        Returns:
            PluginManifest nếu tìm thấy, None nếu không có.
        """
        index = await self._get_index()
        if not index:
            return None

        for entry in index:
            if entry.get("id") == plugin_id:
                return self._parse_entry(entry)

        return None

    async def get_install_url(self, plugin_id: str) -> Optional[str]:
        """
        Lấy source_url để dùng với PluginRegistry.install_plugin().

        Returns:
            URL string hoặc None nếu không tìm thấy plugin.
        """
        index = await self._get_index()
        if not index:
            return None

        for entry in index:
            if entry.get("id") == plugin_id:
                return entry.get("source_url") or entry.get("homepage")

        return None

    def invalidate_cache(self) -> None:
        """Xóa index cache, force fetch lại lần sau."""
        self._index_cache = None
        self._cache_fetched_at = 0.0
        logger.info("[Marketplace] Cache invalidated")

    # ──────────────────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_index(self) -> List[Dict[str, Any]]:
        """
        Lấy plugin index, dùng cache nếu còn hạn.
        Trả về empty list nếu network error.
        """
        now = time.time()
        if (
            self._index_cache is not None
            and now - self._cache_fetched_at < _CACHE_TTL_SECONDS
        ):
            return self._index_cache

        try:
            index = await asyncio.to_thread(self._fetch_index_sync)
            self._index_cache = index
            self._cache_fetched_at = now
            logger.info("[Marketplace] Index fetched | count=%d", len(index))
            return index
        except Exception as exc:
            logger.warning(
                "[Marketplace] Không thể fetch index (offline?): %s",
                exc,
            )
            # Trả về cache cũ nếu còn, otherwise empty
            return self._index_cache or []

    def _fetch_index_sync(self) -> List[Dict[str, Any]]:
        """Sync HTTP fetch để wrap bằng asyncio.to_thread."""
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            self._url,
            headers={"User-Agent": "IronCore-V2/1.0"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=self._timeout) as resp:
            raw = resp.read().decode("utf-8")

        data = json.loads(raw)

        # Index có thể là array hoặc {"plugins": [...]}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("plugins", [])

        return []

    def _matches(self, entry: Dict[str, Any], query: str) -> bool:
        """Kiểm tra một entry có khớp với query không."""
        searchable = " ".join([
            str(entry.get("id", "")),
            str(entry.get("name", "")),
            str(entry.get("description", "")),
            " ".join(entry.get("tags", [])),
        ]).lower()
        return query in searchable

    def _parse_entry(self, entry: Dict[str, Any]) -> Optional[PluginManifest]:
        """Parse một entry từ index thành PluginManifest. None nếu invalid."""
        try:
            return PluginManifest.model_validate(entry)
        except Exception as exc:
            logger.debug(
                "[Marketplace] Entry '%s' không parse được: %s",
                entry.get("id", "?"),
                exc,
            )
            return None
