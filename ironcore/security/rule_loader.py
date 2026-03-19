"""
Dynamic TOML-based policy rule loading and hot-reload support.
"""

from __future__ import annotations

import asyncio
import logging
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ironcore.security.policy_engine import (
    AllowlistRule,
    BaseRule,
    CumulativeRiskBudgetRule,
    DangerousArgPatternRule,
    DenylistRule,
    PolicyEngine,
    RateLimitRule,
    SandboxEscalationRule,
)
from ironcore.security.rbac import Permission, RBACRule

logger = logging.getLogger(__name__)


class RuleLoader:
    """
    Load policy rules from TOML and optionally hot-reload them into a PolicyEngine.

    Supported TOML shape:

    ```toml
    [[rules]]
    type = "denylist"
    denied_tools = ["raw_shell"]

    [[rules]]
    type = "rbac"
    tool_permissions = { rotate_secret = "manage_secrets" }
    ```
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._policy_engine = policy_engine
        self._poll_interval_seconds = max(0.1, poll_interval_seconds)
        self._last_mtime_ns: Optional[int] = None

    @classmethod
    def load_from_toml(cls, path: Path) -> List[BaseRule]:
        """Parse a TOML policy file into rule instances."""
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls._parse_rules(document)

    async def reload_from_file(self, path: Path) -> List[BaseRule]:
        """Load rules from disk and atomically replace the current chain."""
        rules = self.load_from_toml(path)
        self._policy_engine.reload_rules(rules)
        self._last_mtime_ns = path.stat().st_mtime_ns
        logger.info(
            "[RuleLoader] Reloaded policy file | path=%s rule_count=%s",
            path,
            len(rules),
        )
        return rules

    async def watch(
        self,
        path: Path,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """
        Poll a TOML file for changes and hot-reload into the bound PolicyEngine.
        """
        if stop_event is None:
            stop_event = asyncio.Event()

        path = path.resolve()
        if path.exists():
            self._last_mtime_ns = path.stat().st_mtime_ns

        while not stop_event.is_set():
            try:
                current_mtime_ns = path.stat().st_mtime_ns
            except FileNotFoundError:
                await asyncio.sleep(self._poll_interval_seconds)
                continue

            if self._last_mtime_ns is None or current_mtime_ns > self._last_mtime_ns:
                try:
                    await self.reload_from_file(path)
                except Exception as exc:
                    logger.exception("[RuleLoader] Failed to reload policy file %s: %s", path, exc)

            await asyncio.sleep(self._poll_interval_seconds)

    @classmethod
    def _parse_rules(cls, document: Mapping[str, Any]) -> List[BaseRule]:
        if "rules" in document:
            raw_rules = document["rules"]
            if not isinstance(raw_rules, list):
                raise ValueError("'rules' must be an array of tables.")
            return [cls._build_rule(entry) for entry in raw_rules]

        section_order = [
            "dangerous_arg_pattern",
            "denylist",
            "rate_limit",
            "sandbox_escalation",
            "cumulative_risk_budget",
            "rbac",
            "allowlist",
        ]
        rules: List[BaseRule] = []
        for section_name in section_order:
            section = document.get(section_name)
            if isinstance(section, Mapping):
                entry = dict(section)
                entry["type"] = section_name
                rules.append(cls._build_rule(entry))
        return rules

    @classmethod
    def _build_rule(cls, raw_rule: Mapping[str, Any]) -> BaseRule:
        rule_type = str(raw_rule.get("type", "")).strip().lower()
        if not rule_type:
            raise ValueError("Rule entry is missing 'type'.")

        if rule_type == "dangerous_arg_pattern":
            patterns = raw_rule.get("patterns")
            normalized_patterns = None
            if patterns is not None:
                normalized_patterns = [tuple(item) for item in patterns]
            return DangerousArgPatternRule(patterns=normalized_patterns)

        if rule_type == "denylist":
            denied_tools = set(cls._require_list(raw_rule, "denied_tools"))
            return DenylistRule(denied_tools=denied_tools)

        if rule_type == "rate_limit":
            limits_raw = raw_rule.get("limits", {})
            if not isinstance(limits_raw, Mapping):
                raise ValueError("'limits' must be a TOML table.")
            limits = {
                tool_name: (int(values[0]), float(values[1]))
                for tool_name, values in limits_raw.items()
            }
            return RateLimitRule(limits=limits)

        if rule_type == "sandbox_escalation":
            sandboxed_tools = set(cls._require_list(raw_rule, "sandboxed_tools"))
            return SandboxEscalationRule(sandboxed_tools=sandboxed_tools)

        if rule_type == "cumulative_risk_budget":
            max_budget = int(raw_rule.get("max_budget", 100))
            cost_map_raw = raw_rule.get("cost_map")
            cost_map = None
            if cost_map_raw is not None:
                if not isinstance(cost_map_raw, Mapping):
                    raise ValueError("'cost_map' must be a TOML table.")
                cost_map = {str(key).upper(): int(value) for key, value in cost_map_raw.items()}
            return CumulativeRiskBudgetRule(max_budget=max_budget, cost_map=cost_map)

        if rule_type == "rbac":
            tool_permissions_raw = raw_rule.get("tool_permissions", {})
            if not isinstance(tool_permissions_raw, Mapping):
                raise ValueError("'tool_permissions' must be a TOML table.")
            tool_permissions = {
                str(tool_name): Permission(str(permission).lower())
                for tool_name, permission in tool_permissions_raw.items()
            }
            read_only_tools = set(cls._require_list(raw_rule, "read_only_tools", required=False) or [])
            token_secret = raw_rule.get("token_secret")
            if token_secret is not None:
                token_secret = str(token_secret)
            return RBACRule(
                tool_permissions=tool_permissions,
                read_only_tools=read_only_tools or None,
                token_secret=token_secret,
            )

        if rule_type == "allowlist":
            allowed_tools = set(cls._require_list(raw_rule, "allowed_tools"))
            return AllowlistRule(allowed_tools=allowed_tools)

        raise ValueError(f"Unsupported rule type: {rule_type}")

    @staticmethod
    def _require_list(
        raw_rule: Mapping[str, Any],
        key: str,
        required: bool = True,
    ) -> Optional[List[Any]]:
        value = raw_rule.get(key)
        if value is None and not required:
            return None
        if not isinstance(value, list):
            raise ValueError(f"'{key}' must be a TOML array.")
        return value
