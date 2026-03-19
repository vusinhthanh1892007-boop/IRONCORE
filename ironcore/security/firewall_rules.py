"""
Prompt Firewall — Rule DSL & Store (Phase 1, Security V3).

Provides:
  - FirewallRuleAction  : enum of possible gate actions
  - FirewallRule        : Pydantic model describing one rule
  - FirewallRuleStore   : TOML-backed, hot-reloadable rule registry
  - DEFAULT_RULES_PATH  : default path for the custom rules TOML file

Example TOML file (ironcore/security/custom_firewall_rules.toml):

    [[rules]]
    id = "custom-001"
    name = "Block competitor probing"
    pattern = "(?i)tell me about openai"
    category = "custom"
    action = "block"
    severity = "medium"
    enabled = true
    description = "Block attempts to probe us about competitors."
    created_by = "admin"
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import tomllib
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_RULES_PATH = Path(__file__).parent / "custom_firewall_rules.toml"


# ── Enums (plain string-subclass for JSON serialisability) ────────────────────

class FirewallRuleAction(str):
    ALLOW      = "allow"
    WARN       = "warn"
    SANITIZE   = "sanitize"
    BLOCK      = "block"
    QUARANTINE = "quarantine"   # block entire session


VALID_ACTIONS = {
    FirewallRuleAction.ALLOW,
    FirewallRuleAction.WARN,
    FirewallRuleAction.SANITIZE,
    FirewallRuleAction.BLOCK,
    FirewallRuleAction.QUARANTINE,
}

VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_CATEGORIES = {
    "injection", "jailbreak", "data_exfil",
    "role_confusion", "goal_hijacking", "custom",
}


# ── FirewallRule ──────────────────────────────────────────────────────────────

class FirewallRule(BaseModel):
    """A single custom firewall rule evaluated against the sanitised prompt text."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    pattern: str                        # Python regex pattern
    category: str = "custom"
    action: str = FirewallRuleAction.BLOCK
    severity: str = "medium"
    enabled: bool = True
    description: str = ""
    created_by: str = "system"
    created_at: float = Field(default_factory=time.time)

    # Compiled regex — populated after validation
    _compiled: Optional[re.Pattern] = None

    def model_post_init(self, __context: object) -> None:  # noqa: D401
        try:
            self._compiled = re.compile(self.pattern, re.I | re.S)
        except re.error:
            self._compiled = None  # validate_fields() will catch this

    # ------------------------------------------------------------------
    # Validation helpers

    def validate_fields(self) -> List[str]:
        """Return list of validation errors, empty list if valid."""
        errors: List[str] = []
        if not self.name.strip():
            errors.append("name must not be empty")
        if self.action not in VALID_ACTIONS:
            errors.append(f"action must be one of {sorted(VALID_ACTIONS)}")
        if self.severity not in VALID_SEVERITIES:
            errors.append(f"severity must be one of {sorted(VALID_SEVERITIES)}")
        if self.category not in VALID_CATEGORIES:
            errors.append(f"category must be one of {sorted(VALID_CATEGORIES)}")
        # Try to compile the pattern
        try:
            re.compile(self.pattern)
        except re.error as exc:
            errors.append(f"pattern is invalid regex: {exc}")
        return errors

    # ------------------------------------------------------------------
    # Matching

    def match(self, text: str) -> Optional[re.Match]:
        """Return the first regex match in *text*, or None."""
        if not self.enabled:
            return None
        if self._compiled is None:
            try:
                self._compiled = re.compile(self.pattern, re.I | re.S)
            except re.error:
                return None
        return self._compiled.search(text)


# ── FirewallRuleStore ─────────────────────────────────────────────────────────

class FirewallRuleStore:
    """
    In-memory store backed by an optional TOML file.

    Features:
      - load_from_file()  → parse TOML, replace in-memory rules atomically
      - add_rule()        → add rule at runtime + persist to file
      - remove_rule()     → mark disabled + persist
      - get_active_rules() → return enabled rules, ordered by severity (critical first)
      - watch()           → coroutine: poll file for changes and hot-reload
    """

    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, rules_path: Optional[Path] = None) -> None:
        self._path: Optional[Path] = rules_path
        self._rules: List[FirewallRule] = []
        self._lock = asyncio.Lock()
        self._last_mtime_ns: Optional[int] = None

    # ── Loading ──────────────────────────────────────────────────────────────

    def load_from_file(self, path: Optional[Path] = None) -> List[FirewallRule]:
        """
        Parse TOML and replace in-memory rules atomically (sync).

        Returns the loaded rule list.
        """
        target = path or self._path
        if target is None or not target.exists():
            logger.debug("[FirewallRuleStore] No rules file found — using empty rule set.")
            return []

        try:
            raw = tomllib.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.error("[FirewallRuleStore] Failed to parse TOML %s: %s", target, exc)
            return list(self._rules)  # keep existing

        rules: List[FirewallRule] = []
        for entry in raw.get("rules", []):
            try:
                rule = FirewallRule(**entry)
                errs = rule.validate_fields()
                if errs:
                    logger.warning(
                        "[FirewallRuleStore] Rule '%s' skipped — validation errors: %s",
                        entry.get("name", "?"),
                        errs,
                    )
                else:
                    rules.append(rule)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[FirewallRuleStore] Skipping malformed rule entry: %s", exc)

        self._rules = rules
        if target.exists():
            self._last_mtime_ns = target.stat().st_mtime_ns
        logger.info(
            "[FirewallRuleStore] Loaded %d custom rules from %s", len(rules), target
        )
        return rules

    async def async_load_from_file(self, path: Optional[Path] = None) -> List[FirewallRule]:
        """Async wrapper around load_from_file (uses asyncio.Lock for safety)."""
        async with self._lock:
            return self.load_from_file(path)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def add_rule(self, rule: FirewallRule) -> None:
        """Add (or replace) a rule and persist to file if path is set."""
        errs = rule.validate_fields()
        if errs:
            raise ValueError(f"Rule validation failed: {'; '.join(errs)}")

        async with self._lock:
            # Replace if same id
            self._rules = [r for r in self._rules if r.id != rule.id]
            self._rules.append(rule)
            await self._persist()

        logger.info("[FirewallRuleStore] Rule added/updated: id=%s name=%s", rule.id, rule.name)

    async def remove_rule(self, rule_id: str) -> bool:
        """
        Remove a rule by id. Returns True if found, False otherwise.
        """
        async with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.id != rule_id]
            removed = len(self._rules) < before
            if removed:
                await self._persist()

        if removed:
            logger.info("[FirewallRuleStore] Rule removed: id=%s", rule_id)
        return removed

    async def enable_rule(self, rule_id: str, enabled: bool = True) -> bool:
        """Toggle enabled state. Returns True if the rule was found."""
        async with self._lock:
            for rule in self._rules:
                if rule.id == rule_id:
                    rule.enabled = enabled
                    await self._persist()
                    return True
        return False

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_active_rules(self) -> List[FirewallRule]:
        """Return enabled rules sorted: critical → high → medium → low."""
        active = [r for r in self._rules if r.enabled]
        return sorted(active, key=lambda r: self._SEVERITY_ORDER.get(r.severity, 99))

    def get_all_rules(self) -> List[FirewallRule]:
        """Return all rules (enabled and disabled)."""
        return list(self._rules)

    def get_rule(self, rule_id: str) -> Optional[FirewallRule]:
        for r in self._rules:
            if r.id == rule_id:
                return r
        return None

    def rule_count(self) -> int:
        return len(self._rules)

    # ── Hot-reload watcher ───────────────────────────────────────────────────

    async def watch(
        self,
        path: Optional[Path] = None,
        poll_interval_seconds: float = 5.0,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """
        Coroutine: poll the TOML file every *poll_interval_seconds* seconds
        and hot-reload if the modification time changes.
        """
        target = (path or self._path)
        if target is None:
            logger.warning("[FirewallRuleStore] watch() called without a rules path — skipping.")
            return

        stop = stop_event or asyncio.Event()
        target = target.resolve()
        logger.info("[FirewallRuleStore] Watching %s every %.1fs", target, poll_interval_seconds)

        while not stop.is_set():
            try:
                if target.exists():
                    mtime = target.stat().st_mtime_ns
                    if self._last_mtime_ns is None or mtime > self._last_mtime_ns:
                        await self.async_load_from_file(target)
                        logger.info("[FirewallRuleStore] Hot-reloaded rules from %s", target)
            except Exception as exc:  # noqa: BLE001
                logger.error("[FirewallRuleStore] Watch error: %s", exc)

            try:
                await asyncio.wait_for(asyncio.shield(stop.wait()), timeout=poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    # ── Test helper ──────────────────────────────────────────────────────────

    def test_rule(self, rule: FirewallRule, input_text: str) -> dict:
        """
        Dry-run a single rule against *input_text*.
        Returns a dict with 'matched', 'snippet', 'action', 'severity'.
        """
        m = rule.match(input_text)
        if m:
            start = max(0, m.start() - 20)
            end = min(len(input_text), m.end() + 20)
            snippet = input_text[start:end]
        else:
            snippet = ""
        return {
            "matched": m is not None,
            "snippet": snippet,
            "action": rule.action,
            "severity": rule.severity,
            "rule_id": rule.id,
            "rule_name": rule.name,
        }

    # ── Persistence ──────────────────────────────────────────────────────────

    async def _persist(self) -> None:
        """Serialise _rules back to TOML. Called inside _lock."""
        if self._path is None:
            return
        try:
            lines = []
            for r in self._rules:
                lines.append("[[rules]]")
                lines.append(f'id = "{r.id}"')
                lines.append(f'name = "{r.name}"')
                # Escape backslashes for TOML
                safe_pattern = r.pattern.replace("\\", "\\\\")
                lines.append(f'pattern = "{safe_pattern}"')
                lines.append(f'category = "{r.category}"')
                lines.append(f'action = "{r.action}"')
                lines.append(f'severity = "{r.severity}"')
                lines.append(f'enabled = {str(r.enabled).lower()}')
                lines.append(f'description = "{r.description}"')
                lines.append(f'created_by = "{r.created_by}"')
                lines.append(f'created_at = {r.created_at}')
                lines.append("")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("\n".join(lines), encoding="utf-8")
            self._last_mtime_ns = self._path.stat().st_mtime_ns
        except Exception as exc:  # noqa: BLE001
            logger.error("[FirewallRuleStore] Failed to persist rules: %s", exc)
