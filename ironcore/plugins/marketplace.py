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
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import asyncio

from .manifest import PluginManifest

logger = logging.getLogger(__name__)

_DEFAULT_MARKETPLACE_URL = "https://plugins.ironcore.dev/index.json"
_CACHE_TTL_SECONDS = 300   # Cache index 5 phút
_DEFAULT_IRONCORE_VERSION = "2.0.0"
_DEFAULT_MIN_TRUST_SCORE = 60.0


@dataclass
class _VersionConstraintResult:
    compatible: bool
    reasons: List[str]


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

    async def get_plugin_governance(
        self,
        plugin_id: str,
        current_ironcore_version: Optional[str] = None,
        current_python_version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Trả metadata governance cho plugin marketplace:
        - publisher trust / verified signer
        - version compatibility matrix
        - security + dependency metadata
        - review pipeline checklist
        """
        index = await self._get_index()
        if not index:
            return None

        for entry in index:
            if entry.get("id") == plugin_id:
                governance, _ = self._build_governance_summary(
                    entry,
                    current_ironcore_version=current_ironcore_version,
                    current_python_version=current_python_version,
                )
                return governance
        return None

    async def get_install_candidate(
        self,
        plugin_id: str,
        current_ironcore_version: Optional[str] = None,
        current_python_version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Trả gói thông tin trước khi cài plugin:
        - manifest hợp lệ
        - governance metadata
        - quyết định cho phép cài + blockers/warnings
        """
        index = await self._get_index()
        if not index:
            return None

        for entry in index:
            if entry.get("id") != plugin_id:
                continue

            manifest = self._parse_entry(entry)
            if not manifest:
                return None

            governance, review = self._build_governance_summary(
                entry,
                current_ironcore_version=current_ironcore_version,
                current_python_version=current_python_version,
            )
            decision = self._evaluate_install_decision(governance)

            return {
                "manifest": manifest,
                "install_url": entry.get("source_url") or entry.get("homepage"),
                "governance": governance,
                "review_pipeline": review,
                "install_allowed": decision["allowed"],
                "blockers": decision["blockers"],
                "warnings": decision["warnings"],
            }

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

    def _build_governance_summary(
        self,
        entry: Dict[str, Any],
        current_ironcore_version: Optional[str] = None,
        current_python_version: Optional[str] = None,
    ) -> tuple[Dict[str, Any], List[Dict[str, str]]]:
        publisher = self._normalize_publisher(entry)
        compatibility = self._normalize_compatibility(
            entry,
            current_ironcore_version=current_ironcore_version,
            current_python_version=current_python_version,
        )
        security = self._normalize_security(entry)
        dependencies = self._normalize_dependencies(entry)

        review_pipeline = self._build_review_pipeline(
            publisher=publisher,
            compatibility=compatibility,
            security=security,
        )

        governance = {
            "publisher": publisher,
            "compatibility": compatibility,
            "security": security,
            "dependencies": dependencies,
            "trust_score": publisher["trust_score"],
            "verified_signer": publisher["verified_signer"],
        }
        return governance, review_pipeline

    def _normalize_publisher(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        publisher_row = entry.get("publisher") if isinstance(entry.get("publisher"), dict) else {}

        verified_signer = bool(
            publisher_row.get("verified_signer")
            or publisher_row.get("verified")
            or entry.get("verified_signer")
            or entry.get("verified")
        )

        trust_score_raw = (
            publisher_row.get("trust_score")
            if "trust_score" in publisher_row
            else entry.get("trust_score")
        )
        trust_score = self._to_float(trust_score_raw, 80.0 if verified_signer else 50.0)
        trust_score = max(0.0, min(100.0, trust_score))

        return {
            "id": str(publisher_row.get("id") or entry.get("author") or "unknown").strip(),
            "name": str(publisher_row.get("name") or entry.get("author") or "Unknown Publisher").strip(),
            "verified_signer": verified_signer,
            "signing_fingerprint": str(publisher_row.get("signing_fingerprint") or "").strip() or None,
            "trust_score": trust_score,
            "review_status": str(publisher_row.get("review_status") or ("verified" if verified_signer else "community")).strip(),
        }

    def _normalize_compatibility(
        self,
        entry: Dict[str, Any],
        current_ironcore_version: Optional[str] = None,
        current_python_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        compatibility_row = entry.get("compatibility") if isinstance(entry.get("compatibility"), dict) else {}

        ironcore_min = str(
            compatibility_row.get("ironcore_min_version")
            or compatibility_row.get("min_ironcore")
            or entry.get("ironcore_min_version")
            or _DEFAULT_IRONCORE_VERSION
        ).strip()
        ironcore_max_raw = compatibility_row.get("ironcore_max_version") or compatibility_row.get("max_ironcore")
        ironcore_max = str(ironcore_max_raw).strip() if ironcore_max_raw else None

        py_row = compatibility_row.get("python") if isinstance(compatibility_row.get("python"), dict) else {}
        py_min = str(py_row.get("min") or compatibility_row.get("python_min") or "3.10").strip()
        py_max_raw = py_row.get("max") or compatibility_row.get("python_max")
        py_max = str(py_max_raw).strip() if py_max_raw else None

        resolved_ironcore = (current_ironcore_version or os.getenv("IRONCORE_VERSION") or _DEFAULT_IRONCORE_VERSION).strip()
        resolved_python = (
            current_python_version
            or f"{sys.version_info.major}.{sys.version_info.minor}"
        ).strip()

        ironcore_check = self._check_version_constraints(
            current_version=resolved_ironcore,
            min_version=ironcore_min,
            max_version=ironcore_max,
            domain="ironcore",
        )
        python_check = self._check_version_constraints(
            current_version=resolved_python,
            min_version=py_min,
            max_version=py_max,
            domain="python",
        )

        compatibility_matrix = compatibility_row.get("matrix")
        if not isinstance(compatibility_matrix, list):
            compatibility_matrix = []

        return {
            "ironcore_min_version": ironcore_min,
            "ironcore_max_version": ironcore_max,
            "python": {"min": py_min, "max": py_max},
            "matrix": compatibility_matrix,
            "resolved": {
                "ironcore_version": resolved_ironcore,
                "python_version": resolved_python,
            },
            "compatible": ironcore_check.compatible and python_check.compatible,
            "reasons": [*ironcore_check.reasons, *python_check.reasons],
        }

    def _normalize_security(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        security_row = entry.get("security") if isinstance(entry.get("security"), dict) else {}
        vulns = security_row.get("vulnerabilities") if isinstance(security_row.get("vulnerabilities"), dict) else {}

        critical = self._to_int(vulns.get("critical"), 0)
        high = self._to_int(vulns.get("high"), 0)
        medium = self._to_int(vulns.get("medium"), 0)
        low = self._to_int(vulns.get("low"), 0)

        policy_passed = security_row.get("policy_passed")
        if policy_passed is None:
            policy_passed = critical == 0 and high == 0

        return {
            "last_scan_at": security_row.get("last_scan_at"),
            "sbom_url": security_row.get("sbom_url") or security_row.get("sbom"),
            "advisories_url": security_row.get("advisories_url"),
            "vulnerabilities": {
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
            },
            "policy_passed": bool(policy_passed),
        }

    def _normalize_dependencies(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        dep_row = entry.get("dependencies") if isinstance(entry.get("dependencies"), dict) else {}
        declared = dep_row.get("requires") if isinstance(dep_row.get("requires"), list) else entry.get("install_requires", [])
        if not isinstance(declared, list):
            declared = []

        return {
            "requires": [str(item).strip() for item in declared if str(item).strip()],
            "pinning_policy": str(dep_row.get("pinning_policy") or "unspecified").strip(),
            "security_notes": str(dep_row.get("security_notes") or "").strip() or None,
        }

    def _evaluate_install_decision(self, governance: Dict[str, Any]) -> Dict[str, Any]:
        publisher = governance.get("publisher", {})
        compatibility = governance.get("compatibility", {})
        security = governance.get("security", {})
        vulns = security.get("vulnerabilities", {})

        blockers: List[str] = []
        warnings: List[str] = []

        if not compatibility.get("compatible", True):
            reasons = compatibility.get("reasons") or ["incompatible runtime constraints"]
            blockers.append("Compatibility check failed: " + "; ".join(str(item) for item in reasons))

        if self._to_int(vulns.get("critical"), 0) > 0:
            blockers.append("Security policy blocked: critical vulnerabilities detected")
        if self._to_int(vulns.get("high"), 0) > 0:
            blockers.append("Security policy blocked: high vulnerabilities detected")
        if security.get("policy_passed") is False:
            blockers.append("Security policy blocked: publisher policy check failed")

        if not publisher.get("verified_signer", False):
            warnings.append("Publisher signer is not verified")

        trust_min = self._to_float(os.getenv("IRONCORE_MARKETPLACE_MIN_TRUST_SCORE"), _DEFAULT_MIN_TRUST_SCORE)
        trust_score = self._to_float(publisher.get("trust_score"), 0.0)
        if trust_score < trust_min:
            warnings.append(
                f"Publisher trust score ({trust_score:.1f}) is below recommended threshold ({trust_min:.1f})"
            )

        return {
            "allowed": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
        }

    def _build_review_pipeline(
        self,
        publisher: Dict[str, Any],
        compatibility: Dict[str, Any],
        security: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        trust_score = self._to_float(publisher.get("trust_score"), 0.0)
        trust_min = self._to_float(os.getenv("IRONCORE_MARKETPLACE_MIN_TRUST_SCORE"), _DEFAULT_MIN_TRUST_SCORE)
        verified = bool(publisher.get("verified_signer"))

        vulns = security.get("vulnerabilities", {})
        critical = self._to_int(vulns.get("critical"), 0)
        high = self._to_int(vulns.get("high"), 0)

        publisher_state = "pass" if verified else "warn"
        trust_state = "pass" if trust_score >= trust_min else "warn"
        compatibility_state = "pass" if compatibility.get("compatible", True) else "fail"
        security_state = "pass" if (critical == 0 and high == 0 and security.get("policy_passed", True)) else "fail"

        return [
            {"stage": "publisher_identity", "status": publisher_state},
            {"stage": "trust_score", "status": trust_state},
            {"stage": "compatibility_matrix", "status": compatibility_state},
            {"stage": "security_metadata", "status": security_state},
        ]

    def _check_version_constraints(
        self,
        current_version: str,
        min_version: Optional[str],
        max_version: Optional[str],
        domain: str,
    ) -> _VersionConstraintResult:
        reasons: List[str] = []

        current_tuple = self._parse_version_tuple(current_version)
        min_tuple = self._parse_version_tuple(min_version) if min_version else None
        max_tuple = self._parse_version_tuple(max_version) if max_version else None

        if current_tuple is None:
            reasons.append(f"{domain} current version is invalid: '{current_version}'")
            return _VersionConstraintResult(compatible=False, reasons=reasons)

        if min_version and min_tuple is None:
            reasons.append(f"{domain} min version format is invalid: '{min_version}'")
            return _VersionConstraintResult(compatible=False, reasons=reasons)

        if max_version and max_tuple is None:
            reasons.append(f"{domain} max version format is invalid: '{max_version}'")
            return _VersionConstraintResult(compatible=False, reasons=reasons)

        compatible = True
        if min_tuple and current_tuple < min_tuple:
            compatible = False
            reasons.append(f"{domain} {current_version} < min {min_version}")
        if max_tuple and current_tuple > max_tuple:
            compatible = False
            reasons.append(f"{domain} {current_version} > max {max_version}")

        return _VersionConstraintResult(compatible=compatible, reasons=reasons)

    def _parse_version_tuple(self, value: Optional[str]) -> Optional[tuple[int, ...]]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None

        parts: List[int] = []
        for part in text.split("."):
            if not part.isdigit():
                return None
            parts.append(int(part))
        return tuple(parts)

    def _to_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _to_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default
