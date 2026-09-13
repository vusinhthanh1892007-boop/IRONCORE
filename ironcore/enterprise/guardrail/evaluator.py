"""
Guardrail Evaluator — Phase 3, Security V3.

Fast async pipeline that checks text (input or output) against all active
Guardrail rules in priority order.

Evaluation order per rule:
  1. KEYWORD → frozenset lookup (O(1) per keyword)
  2. REGEX   → pre-compiled pattern (.search)
  3. LENGTH  → character/token count check
  4. LLM     → cheap LLM judge (slow path, only if needed)

First violation with remedy=BLOCK stops the chain immediately.
All WARN, REWRITE, APPEND violations are collected and returned together.

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ironcore.enterprise.guardrail.rules_store import (
    GuardrailConditionType,
    GuardrailRemedy,
    GuardrailRule,
    GuardrailRulesStore,
    GuardrailScope,
    GuardrailViolation,
)

logger = logging.getLogger(__name__)

# Simple word-tokenizer fallback (tokens ≈ words + punctuation)
_TOKEN_RE = re.compile(r"\S+")


def _approx_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


class GuardrailEvaluator:
    """
    Async evaluator for Guardrail policies.

    Args:
        rule_store: Shared GuardrailRulesStore instance.

    Usage::

        evaluator = GuardrailEvaluator(store)

        result = await evaluator.evaluate_input(user_prompt, session_id="s1")
        if result.blocked:
            raise PermissionError(result.block_reason)

        result = await evaluator.evaluate_output(llm_response, session_id="s1")
        final_text = result.rewritten_text or llm_response
    """

    def __init__(self, rule_store: GuardrailRulesStore) -> None:
        self._store = rule_store
        # Pre-compile regex rules and cache them
        self._compiled_regex: Dict[str, re.Pattern] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    async def evaluate_input(
        self, text: str, session_id: str = ""
    ) -> "EvaluationResult":
        """Check user input against input-scoped and both-scoped rules."""
        rules = await self._store.get_active_rules(scope=None)
        input_rules = [
            r for r in rules
            if r.scope.value in (GuardrailScope.INPUT.value, GuardrailScope.BOTH.value)
        ]
        return await self._run_pipeline(text, input_rules, session_id)

    async def evaluate_output(
        self, text: str, session_id: str = ""
    ) -> "EvaluationResult":
        """Check LLM output against output-scoped and both-scoped rules."""
        rules = await self._store.get_active_rules(scope=None)
        output_rules = [
            r for r in rules
            if r.scope.value in (GuardrailScope.OUTPUT.value, GuardrailScope.BOTH.value)
        ]
        return await self._run_pipeline(text, output_rules, session_id)

    async def test_rule(
        self, rule: GuardrailRule, text: str
    ) -> Dict[str, Any]:
        """
        Dry-run one rule against text (no stats update).
        Used by the Guardrail Studio "Test" button in the UI.
        """
        violated, evidence, rewritten = await self._evaluate_rule(rule, text)
        return {
            "rule_id": rule.rule_id,
            "rule_name": rule.name,
            "matched": violated,
            "evidence": evidence,
            "remedy": rule.remedy.value,
            "rewritten_text": rewritten,
        }

    # ── Pipeline ───────────────────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        text: str,
        rules: List[GuardrailRule],
        session_id: str,
    ) -> "EvaluationResult":
        """
        Run rules in priority order.

        Returns EvaluationResult with:
          - blocked: True if any BLOCK rule matched
          - violations: list of all matched violations (WARN/REWRITE/APPEND/BLOCK)
          - rewritten_text: text after applying REWRITE/APPEND remedies
        """
        violations: List[GuardrailViolation] = []
        current_text = text
        blocked = False
        block_reason = ""

        for rule in rules:
            violated, evidence, rewritten = await self._evaluate_rule(rule, current_text)

            # Update stats in background (fire-and-forget)
            try:
                import asyncio
                asyncio.ensure_future(
                    self._store.increment_stats(rule.rule_id, violated=violated)
                )
            except Exception:  # noqa: BLE001
                pass

            if not violated:
                continue

            violation = GuardrailViolation(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                category=rule.category.value,
                scope=rule.scope.value,
                remedy=rule.remedy.value,
                remedy_text=rule.remedy_text,
                evidence=evidence[:200],
                rewritten_text=rewritten,
            )
            violations.append(violation)

            logger.info(
                "[GuardrailEvaluator] Violation | rule=%s remedy=%s session=%s",
                rule.name, rule.remedy.value, session_id,
            )

            if rule.remedy == GuardrailRemedy.BLOCK:
                blocked = True
                block_reason = (
                    f"Guardrail rule '{rule.name}' (category={rule.category.value}) "
                    f"blocked this {'request' if rule.scope == GuardrailScope.INPUT else 'response'}."
                )
                break  # BLOCK is terminal

            elif rule.remedy == GuardrailRemedy.REWRITE and rewritten:
                current_text = rewritten

            elif rule.remedy == GuardrailRemedy.APPEND:
                current_text = current_text + "\n\n" + rule.remedy_text

        return EvaluationResult(
            original_text=text,
            rewritten_text=current_text if current_text != text else None,
            violations=violations,
            blocked=blocked,
            block_reason=block_reason,
            rules_evaluated=len(rules),
        )

    async def _evaluate_rule(
        self,
        rule: GuardrailRule,
        text: str,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Evaluate one rule against text.
        Returns (violated, evidence_snippet, rewritten_text).
        """
        ctype = rule.condition_type
        params = rule.condition_params

        if ctype == GuardrailConditionType.KEYWORD:
            return self._eval_keyword(rule, text, params)

        elif ctype == GuardrailConditionType.REGEX:
            return self._eval_regex(rule, text, params)

        elif ctype == GuardrailConditionType.LENGTH:
            return self._eval_length(text, params)

        elif ctype == GuardrailConditionType.LLM:
            return await self._eval_llm(text, params)

        return False, "", None

    # ── Condition evaluators ───────────────────────────────────────────────────

    @staticmethod
    def _eval_keyword(
        rule: GuardrailRule,
        text: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[str]]:
        """Case-insensitive keyword scan (whole-word optional)."""
        keywords: List[str] = params.get("keywords", [])
        whole_word: bool = params.get("whole_word", False)
        lower = text.lower()

        for kw in keywords:
            kw_lower = kw.lower()
            if whole_word:
                pattern = re.compile(r"\b" + re.escape(kw_lower) + r"\b")
                m = pattern.search(lower)
                if m:
                    start = max(0, m.start() - 30)
                    end = min(len(text), m.end() + 30)
                    evidence = text[start:end]
                    rewritten = text.replace(kw, rule.remedy_text) if rule.remedy == GuardrailRemedy.REWRITE else None
                    return True, evidence, rewritten
            elif kw_lower in lower:
                idx = lower.index(kw_lower)
                start = max(0, idx - 30)
                end = min(len(text), idx + len(kw) + 30)
                evidence = text[start:end]
                rewritten = text.replace(kw, rule.remedy_text) if rule.remedy == GuardrailRemedy.REWRITE else None
                return True, evidence, rewritten

        return False, "", None

    def _eval_regex(
        self,
        rule: GuardrailRule,
        text: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[str]]:
        """Pre-compiled regex match."""
        pattern_str: str = params.get("pattern", "")
        if not pattern_str:
            return False, "", None

        if rule.rule_id not in self._compiled_regex:
            try:
                self._compiled_regex[rule.rule_id] = re.compile(pattern_str, re.I | re.S)
            except re.error:
                logger.warning("[GuardrailEvaluator] Bad regex in rule %s", rule.rule_id)
                return False, "", None

        m = self._compiled_regex[rule.rule_id].search(text)
        if not m:
            return False, "", None

        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        evidence = text[start:end]
        rewritten: Optional[str] = None
        if rule.remedy == GuardrailRemedy.REWRITE:
            rewritten = self._compiled_regex[rule.rule_id].sub(rule.remedy_text, text, count=1)
        return True, evidence, rewritten

    @staticmethod
    def _eval_length(
        text: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[str]]:
        """Length constraint check."""
        max_chars: Optional[int] = params.get("max_chars")
        max_tokens: Optional[int] = params.get("max_tokens")
        min_chars: Optional[int] = params.get("min_chars")

        char_count = len(text)
        token_count = _approx_tokens(text)

        if max_chars is not None and char_count > max_chars:
            return True, f"[length: {char_count} chars > max {max_chars}]", None
        if max_tokens is not None and token_count > max_tokens:
            return True, f"[length: ~{token_count} tokens > max {max_tokens}]", None
        if min_chars is not None and char_count < min_chars:
            return True, f"[length: {char_count} chars < min {min_chars}]", None
        return False, "", None

    @staticmethod
    async def _eval_llm(
        text: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[str]]:
        """
        LLM-based classification (slow path).
        Returns (violated, evidence, None) — no rewrite for LLM condition.
        
        Security Design:
          Enforces Fail-Closed by default (IRONCORE_GUARDRAIL_FAIL_CLOSED=true).
          If the LLM judge fails or is unreachable, the request is flagged/blocked
          rather than silently permitted, preventing adversarial bypass during outages.
        """
        judge_prompt: str = params.get("judge_prompt", "Does this text violate any policy?")
        fail_closed: bool = params.get(
            "fail_closed",
            os.getenv("IRONCORE_GUARDRAIL_FAIL_CLOSED", "true").lower() in ("true", "1", "yes"),
        )
        try:
            from ironcore.core.llm_bridge import LLMBridge, ModelConfig  # type: ignore
            bridge = LLMBridge()
            truncated = text[:800]
            prompt = (
                f"{judge_prompt}\n\n"
                f"Text:\n{truncated}\n\n"
                "Respond with JSON only: {\"violated\": true|false, \"reason\": \"...\"}"
            )
            response = await bridge.call_llm(
                messages=[{"role": "user", "content": prompt}],
                model_config=ModelConfig(model_id="claude-3-haiku-20240307", max_output_tokens=64),
            )
            import json
            data = json.loads(response.content)
            violated = bool(data.get("violated", False))
            reason = str(data.get("reason", ""))[:200]
            return violated, reason, None
        except Exception as exc:  # noqa: BLE001
            if fail_closed:
                logger.error(
                    "[GuardrailEvaluator] LLM judge failed (%s: %s) — enforcing FAIL-CLOSED security policy",
                    exc.__class__.__name__, exc,
                )
                return True, f"[SECURITY AUDIT] LLM judge unavailable ({exc.__class__.__name__}): fail-closed policy enforced", None
            else:
                logger.warning(
                    "[GuardrailEvaluator] LLM judge failed (%s: %s) — fail-open policy active, permitting text",
                    exc.__class__.__name__, exc,
                )
                return False, f"[FAIL-OPEN] LLM judge unavailable ({exc.__class__.__name__})", None


# ── EvaluationResult ──────────────────────────────────────────────────────────

class EvaluationResult(BaseModel):
    """Result of running the guardrail pipeline against a text."""

    original_text: str
    rewritten_text: Optional[str] = None    # None means no change
    violations: List[GuardrailViolation] = Field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""
    rules_evaluated: int = 0

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    @property
    def final_text(self) -> str:
        """The text to use after guardrail processing."""
        return self.rewritten_text if self.rewritten_text is not None else self.original_text

    def to_summary(self) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "violation_count": len(self.violations),
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "remedy": v.remedy,
                    "evidence": v.evidence,
                }
                for v in self.violations
            ],
            "rules_evaluated": self.rules_evaluated,
            "text_was_modified": self.rewritten_text is not None,
        }


