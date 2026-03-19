"""
Guardrail Studio — Rule Store (Phase 3, Security V3).

Persistent SQLite-backed store for Guardrail policy rules.
These rules define content-level policies applied AFTER the Prompt Firewall
(which handles injection/jailbreak). Guardrail handles:
  - Topic restrictions  (e.g., "no discussions of competitor products")
  - Output constraints  (e.g., "max response length", "no profanity")
  - Compliance filters  (e.g., "no financial advice", "must include disclaimer")
  - Persona guards     (e.g., "must stay in customer-support role")

Each rule has:
  - A `condition_type` deciding HOW to evaluate it (regex/keyword/length/llm)
  - A `scope` saying WHERE to apply it (input/output/both)
  - A `remedy` telling WHAT to do on violation (block/warn/rewrite/append)

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_DB_PATH = Path(
    os.environ.get(
        "IRONCORE_GUARDRAIL_DB_PATH",
        str(Path.home() / ".ironcore" / "guardrail.db"),
    )
)


# ── Enums ─────────────────────────────────────────────────────────────────────

class GuardrailScope(str, Enum):
    INPUT  = "input"    # check user prompt
    OUTPUT = "output"   # check LLM response
    BOTH   = "both"     # check both


class GuardrailConditionType(str, Enum):
    REGEX    = "regex"     # pattern match
    KEYWORD  = "keyword"   # case-insensitive keyword list
    LENGTH   = "length"    # max/min token/char count
    LLM      = "llm"       # LLM-based classification (slow path)


class GuardrailRemedy(str, Enum):
    BLOCK   = "block"    # halt the request/response entirely
    WARN    = "warn"     # allow but emit a warning event
    REWRITE = "rewrite"  # replace violating text with `remedy_text`
    APPEND  = "append"   # append `remedy_text` to the response


class GuardrailCategory(str, Enum):
    TOPIC_RESTRICTION = "topic_restriction"
    OUTPUT_CONSTRAINT = "output_constraint"
    COMPLIANCE        = "compliance"
    PERSONA_GUARD     = "persona_guard"
    CUSTOM            = "custom"


# ── Models ─────────────────────────────────────────────────────────────────────

class GuardrailRule(BaseModel):
    """One guardrail policy rule."""

    rule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    category: GuardrailCategory = GuardrailCategory.CUSTOM
    scope: GuardrailScope = GuardrailScope.BOTH
    condition_type: GuardrailConditionType = GuardrailConditionType.KEYWORD
    # Condition parameters (interpreted per condition_type)
    condition_params: Dict[str, Any] = Field(default_factory=dict)
    # E.g. for KEYWORD: {"keywords": ["bad_word", "competitor_name"]}
    # E.g. for REGEX:   {"pattern": "(?i)your_pattern"}
    # E.g. for LENGTH:  {"max_chars": 4000, "max_tokens": 1000}
    # E.g. for LLM:     {"judge_prompt": "Does this text contain financial advice?"}
    remedy: GuardrailRemedy = GuardrailRemedy.WARN
    remedy_text: str = ""   # used by REWRITE/APPEND
    enabled: bool = True
    priority: int = 100     # lower number = evaluated first
    created_by: str = "admin"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    # Stats (updated by evaluator, not persisted as Pydantic fields)
    total_evaluations: int = 0
    total_violations: int = 0

    def validate_fields(self) -> List[str]:
        """Return list of validation errors."""
        errors: List[str] = []
        if not self.name.strip():
            errors.append("name must not be empty")
        if self.priority < 0:
            errors.append("priority must be >= 0")
        if self.condition_type == GuardrailConditionType.KEYWORD:
            kws = self.condition_params.get("keywords", [])
            if not isinstance(kws, list) or len(kws) == 0:
                errors.append("KEYWORD condition requires condition_params.keywords (non-empty list)")
        elif self.condition_type == GuardrailConditionType.REGEX:
            if not self.condition_params.get("pattern"):
                errors.append("REGEX condition requires condition_params.pattern")
            else:
                import re
                try:
                    re.compile(self.condition_params["pattern"])
                except re.error as exc:
                    errors.append(f"REGEX pattern invalid: {exc}")
        elif self.condition_type == GuardrailConditionType.LENGTH:
            if "max_chars" not in self.condition_params and "max_tokens" not in self.condition_params:
                errors.append("LENGTH condition requires max_chars or max_tokens in condition_params")
        return errors


class GuardrailViolation(BaseModel, frozen=True):
    """Result of a rule violation during evaluation."""

    rule_id: str
    rule_name: str
    category: str
    scope: str
    remedy: str
    remedy_text: str
    evidence: str           # snippet that triggered the violation
    rewritten_text: Optional[str] = None  # populated if remedy==REWRITE


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS guardrail_rules (
    rule_id          TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL,
    scope            TEXT NOT NULL,
    condition_type   TEXT NOT NULL,
    condition_params TEXT NOT NULL DEFAULT '{}',
    remedy           TEXT NOT NULL,
    remedy_text      TEXT NOT NULL DEFAULT '',
    enabled          INTEGER NOT NULL DEFAULT 1,
    priority         INTEGER NOT NULL DEFAULT 100,
    created_by       TEXT NOT NULL DEFAULT 'admin',
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    total_evaluations INTEGER NOT NULL DEFAULT 0,
    total_violations  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_gr_enabled  ON guardrail_rules(enabled);
CREATE INDEX IF NOT EXISTS idx_gr_priority ON guardrail_rules(priority);
CREATE INDEX IF NOT EXISTS idx_gr_category ON guardrail_rules(category);
"""


# ── GuardrailRulesStore ────────────────────────────────────────────────────────

class GuardrailRulesStore:
    """
    SQLite-backed persistent store for Guardrail policy rules.

    All operations are async-safe. A shared instance is used across the app.

    Usage::

        store = GuardrailRulesStore()
        await store.initialize()

        rule = GuardrailRule(
            name="No financial advice",
            category=GuardrailCategory.COMPLIANCE,
            scope=GuardrailScope.OUTPUT,
            condition_type=GuardrailConditionType.KEYWORD,
            condition_params={"keywords": ["invest in", "buy stock", "guaranteed returns"]},
            remedy=GuardrailRemedy.BLOCK,
        )
        await store.add_rule(rule)
        rules = await store.get_active_rules(scope=GuardrailScope.OUTPUT)
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = (db_path or _DB_PATH).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        """Create schema. Idempotent."""
        if self._initialized:
            return
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        self._initialized = True
        logger.info("[GuardrailRulesStore] Initialized db=%s", self._db_path)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def add_rule(self, rule: GuardrailRule) -> GuardrailRule:
        """Insert or replace a rule. Returns the rule with timestamps updated."""
        errs = rule.validate_fields()
        if errs:
            raise ValueError(f"Rule validation failed: {'; '.join(errs)}")

        rule = rule.model_copy(update={"updated_at": time.time()})
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO guardrail_rules
                    (rule_id, name, description, category, scope, condition_type,
                     condition_params, remedy, remedy_text, enabled, priority,
                     created_by, created_at, updated_at, total_evaluations, total_violations)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rule.rule_id, rule.name, rule.description,
                    rule.category.value, rule.scope.value,
                    rule.condition_type.value,
                    json.dumps(rule.condition_params),
                    rule.remedy.value, rule.remedy_text,
                    int(rule.enabled), rule.priority,
                    rule.created_by, rule.created_at, rule.updated_at,
                    rule.total_evaluations, rule.total_violations,
                ),
            )
            await db.commit()
        logger.info("[GuardrailRulesStore] Rule saved: id=%s name=%s", rule.rule_id, rule.name)
        return rule

    async def get_rule(self, rule_id: str) -> Optional[GuardrailRule]:
        """Return one rule by id, or None."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                "SELECT * FROM guardrail_rules WHERE rule_id=?", (rule_id,)
            ) as cur:
                row = await cur.fetchone()
        return self._row_to_rule(row) if row else None

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule. Returns True if deleted."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "DELETE FROM guardrail_rules WHERE rule_id=?", (rule_id,)
            )
            deleted = cur.rowcount > 0
            await db.commit()
        if deleted:
            logger.info("[GuardrailRulesStore] Rule deleted: id=%s", rule_id)
        return deleted

    async def enable_rule(self, rule_id: str, enabled: bool) -> bool:
        """Toggle rule enabled state."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "UPDATE guardrail_rules SET enabled=?, updated_at=? WHERE rule_id=?",
                (int(enabled), time.time(), rule_id),
            )
            ok = cur.rowcount > 0
            await db.commit()
        return ok

    async def list_rules(
        self,
        category: Optional[str] = None,
        scope: Optional[str] = None,
        enabled_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> List[GuardrailRule]:
        """List rules with optional filters, ordered by priority ASC."""
        conditions: List[str] = []
        params: List[Any] = []
        if category:
            conditions.append("category=?")
            params.append(category)
        if scope and scope != "both":
            conditions.append("(scope=? OR scope='both')")
            params.append(scope)
        if enabled_only:
            conditions.append("enabled=1")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])

        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute(
                f"SELECT * FROM guardrail_rules {where} ORDER BY priority ASC LIMIT ? OFFSET ?",
                params,
            ) as cur:
                rows = await cur.fetchall()
        return [self._row_to_rule(r) for r in rows]

    async def get_active_rules(
        self, scope: Optional[GuardrailScope] = None
    ) -> List[GuardrailRule]:
        """Return enabled rules for a given scope, priority-ordered."""
        scope_val = scope.value if scope else None
        return await self.list_rules(scope=scope_val, enabled_only=True)

    async def increment_stats(
        self, rule_id: str, violated: bool
    ) -> None:
        """Increment evaluation/violation counters for a rule."""
        async with aiosqlite.connect(str(self._db_path)) as db:
            if violated:
                await db.execute(
                    "UPDATE guardrail_rules SET total_evaluations=total_evaluations+1, "
                    "total_violations=total_violations+1 WHERE rule_id=?",
                    (rule_id,),
                )
            else:
                await db.execute(
                    "UPDATE guardrail_rules SET total_evaluations=total_evaluations+1 WHERE rule_id=?",
                    (rule_id,),
                )
            await db.commit()

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_rule(row: tuple) -> GuardrailRule:
        """Map a DB row tuple to GuardrailRule. Column order must match schema."""
        (
            rule_id, name, description, category, scope, condition_type,
            condition_params_json, remedy, remedy_text, enabled, priority,
            created_by, created_at, updated_at, total_evals, total_viols,
        ) = row
        return GuardrailRule(
            rule_id=rule_id,
            name=name,
            description=description,
            category=GuardrailCategory(category),
            scope=GuardrailScope(scope),
            condition_type=GuardrailConditionType(condition_type),
            condition_params=json.loads(condition_params_json),
            remedy=GuardrailRemedy(remedy),
            remedy_text=remedy_text or "",
            enabled=bool(enabled),
            priority=priority,
            created_by=created_by,
            created_at=created_at,
            updated_at=updated_at,
            total_evaluations=total_evals,
            total_violations=total_viols,
        )
