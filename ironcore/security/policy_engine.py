"""
IronCore: Policy Engine
=======================
Rule-based permission enforcement layer that sits between the agent's
decision-making and actual tool execution.

Every Action must pass through PolicyEngine.evaluate() before reaching
the tool handler. The engine checks:
  1. Tool allowlist / denylist
  2. Rate limits per tool (prevents runaway loops)
  3. Argument pattern guards (deny known dangerous patterns)
  4. Session-level cumulative risk budget

Design principles (SOLID):
  - Each Rule is a standalone evaluable unit (Single Responsibility).
  - New rules are added by extending BaseRule (Open/Closed).
  - PolicyEngine only calls evaluate() on rules (Dependency Inversion).

Author: The Architect (IronCore Project)
"""

from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from threading import RLock
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Result Model
# ──────────────────────────────────────────────────────────────────────────────

class PolicyVerdict(Enum):
    ALLOW = auto()
    DENY = auto()
    REQUIRE_SANDBOX = auto()   # Allow, but escalate to sandboxed execution


@dataclass
class PolicyResult:
    """
    Result of a policy evaluation for a single action.

    Attributes:
        verdict     : ALLOW / DENY / REQUIRE_SANDBOX.
        rule_name   : Name of the rule that produced this verdict.
        reason      : Human-readable explanation.
        metadata    : Optional extra data (e.g., remaining rate-limit budget).
    """
    verdict: PolicyVerdict
    rule_name: str
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.verdict != PolicyVerdict.DENY


# ──────────────────────────────────────────────────────────────────────────────
# Base Rule
# ──────────────────────────────────────────────────────────────────────────────

class BaseRule(ABC):
    """
    Abstract base for all policy rules.

    Subclass this and implement evaluate() to add custom enforcement logic.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique rule identifier shown in PolicyResult.rule_name."""

    @abstractmethod
    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        """
        Evaluate whether the action is permitted.

        Args:
            tool_name: The tool being invoked.
            args:      The arguments passed to the tool.
            context:   Session-level context (iteration, history length, etc.).

        Returns:
            PolicyResult with ALLOW, DENY, or REQUIRE_SANDBOX.
        """


# ──────────────────────────────────────────────────────────────────────────────
# Concrete Rules
# ──────────────────────────────────────────────────────────────────────────────

class AllowlistRule(BaseRule):
    """
    Deny any tool not explicitly listed in the allowlist.

    Use this in high-security deployments where the tool surface must be
    tightly controlled.
    """

    def __init__(self, allowed_tools: Set[str]) -> None:
        self._allowed = allowed_tools

    @property
    def name(self) -> str:
        return "allowlist"

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        if tool_name in self._allowed:
            return PolicyResult(
                verdict=PolicyVerdict.ALLOW,
                rule_name=self.name,
                reason=f"'{tool_name}' is in the tool allowlist.",
            )
        return PolicyResult(
            verdict=PolicyVerdict.DENY,
            rule_name=self.name,
            reason=(
                f"'{tool_name}' is not in the allowlist. "
                f"Permitted tools: {sorted(self._allowed)}"
            ),
        )


class DenylistRule(BaseRule):
    """
    Explicitly block a set of tool names regardless of other rules.

    Evaluated FIRST in the chain — a match here short-circuits all others.
    """

    def __init__(self, denied_tools: Set[str]) -> None:
        self._denied = denied_tools

    @property
    def name(self) -> str:
        return "denylist"

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        if tool_name in self._denied:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                rule_name=self.name,
                reason=f"'{tool_name}' is explicitly denied by policy.",
            )
        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            rule_name=self.name,
            reason=f"'{tool_name}' not in denylist.",
        )


class RateLimitRule(BaseRule):
    """
    Enforce a maximum call frequency per tool within a sliding time window.

    Example: Limit 'web_search' to 10 calls per 60 seconds.

    Args:
        limits: Dict mapping tool_name → (max_calls, window_seconds).
                Any tool not listed is unlimited.
    """

    def __init__(self, limits: Dict[str, tuple[int, float]]) -> None:
        self._limits = limits
        # Stores list of call timestamps per tool
        self._call_log: Dict[str, List[float]] = {}

    @property
    def name(self) -> str:
        return "rate_limit"

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        if tool_name not in self._limits:
            return PolicyResult(
                verdict=PolicyVerdict.ALLOW,
                rule_name=self.name,
                reason=f"No rate limit configured for '{tool_name}'.",
            )

        max_calls, window_s = self._limits[tool_name]
        now = time.time()

        # Prune stale entries outside the window
        calls = self._call_log.setdefault(tool_name, [])
        self._call_log[tool_name] = [t for t in calls if now - t < window_s]

        if len(self._call_log[tool_name]) >= max_calls:
            oldest = self._call_log[tool_name][0]
            wait = window_s - (now - oldest)
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                rule_name=self.name,
                reason=(
                    f"Rate limit exceeded for '{tool_name}': "
                    f"{max_calls} calls per {window_s}s. "
                    f"Retry in {wait:.1f}s."
                ),
                metadata={"retry_after_s": wait},
            )

        # Record this call
        self._call_log[tool_name].append(now)
        remaining = max_calls - len(self._call_log[tool_name])
        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            rule_name=self.name,
            reason=f"Rate limit OK for '{tool_name}' ({remaining} calls remaining).",
            metadata={"remaining": remaining},
        )


class DangerousArgPatternRule(BaseRule):
    """
    Scan tool arguments for known dangerous patterns and deny if found.

    Guards against prompt-injection artifacts that try to abuse tools.
    Examples: shell injection in 'command' args, path traversal in file ops.

    Args:
        patterns: List of (arg_key, regex_pattern) tuples to block.
    """

    DEFAULT_PATTERNS: List[tuple[str, str]] = [
        # Block shell injection in any 'command' or 'cmd' argument
        ("command", r"[;&|`$\\(]{2,}"),
        ("cmd",     r"[;&|`$\\(]{2,}"),
        # Block path traversal in file-related arguments
        ("path",    r"\.\./"),
        ("file",    r"\.\./"),
        ("filename",r"\.\./"),
        # Block known dangerous Python builtins being passed as code
        ("code",    r"(os\.system|subprocess|__import__|exec\s*\()"),
        ("script",  r"(os\.system|subprocess|__import__|exec\s*\()"),
    ]

    def __init__(
        self,
        patterns: Optional[List[tuple[str, str]]] = None,
    ) -> None:
        self._checks = [
            (key, re.compile(pat, re.IGNORECASE))
            for key, pat in (patterns or self.DEFAULT_PATTERNS)
        ]

    @property
    def name(self) -> str:
        return "dangerous_arg_pattern"

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        for arg_key, compiled_pat in self._checks:
            value = args.get(arg_key)
            if isinstance(value, str) and compiled_pat.search(value):
                return PolicyResult(
                    verdict=PolicyVerdict.DENY,
                    rule_name=self.name,
                    reason=(
                        f"Dangerous pattern detected in arg '{arg_key}' "
                        f"for tool '{tool_name}'. Value blocked by security policy."
                    ),
                )
        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            rule_name=self.name,
            reason="No dangerous argument patterns found.",
        )


class SandboxEscalationRule(BaseRule):
    """
    Automatically escalate to sandboxed execution for high-risk tools,
    even when the action itself does not request it.

    This acts as a safety net for tools that interact with the filesystem,
    network, or execute arbitrary code.
    """

    def __init__(self, sandboxed_tools: Set[str]) -> None:
        self._sandboxed = sandboxed_tools

    @property
    def name(self) -> str:
        return "sandbox_escalation"

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        if tool_name in self._sandboxed:
            return PolicyResult(
                verdict=PolicyVerdict.REQUIRE_SANDBOX,
                rule_name=self.name,
                reason=(
                    f"'{tool_name}' is designated as a sandboxed tool. "
                    "Execution will be isolated in a Docker container."
                ),
            )
        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            rule_name=self.name,
            reason=f"'{tool_name}' does not require sandbox escalation.",
        )


class CumulativeRiskBudgetRule(BaseRule):
    """
    Track cumulative risk across the session and deny when budget is exhausted.

    Each RiskLevel contributes points to a session-level counter.
    When the total exceeds max_budget, all HIGH/CRITICAL actions are blocked.

    Args:
        max_budget : Total risk points allowed per session.
        cost_map   : Points per RiskLevel string name (from Action.risk_level.name).
    """

    DEFAULT_COST: Dict[str, int] = {
        "LOW":      1,
        "MEDIUM":   3,
        "HIGH":     10,
        "CRITICAL": 25,
    }

    def __init__(
        self,
        max_budget: int = 100,
        cost_map: Optional[Dict[str, int]] = None,
    ) -> None:
        self._max_budget = max_budget
        self._cost_map = cost_map or self.DEFAULT_COST
        self._spent: int = 0

    @property
    def name(self) -> str:
        return "cumulative_risk_budget"

    @property
    def remaining_budget(self) -> int:
        return max(0, self._max_budget - self._spent)

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PolicyResult:
        risk_name: str = context.get("risk_level", "LOW")
        cost = self._cost_map.get(risk_name, 1)

        if self._spent + cost > self._max_budget:
            return PolicyResult(
                verdict=PolicyVerdict.DENY,
                rule_name=self.name,
                reason=(
                    f"Session risk budget exhausted. "
                    f"Spent={self._spent}/{self._max_budget}, "
                    f"action cost={cost} ({risk_name}). "
                    "Start a new session to reset."
                ),
                metadata={
                    "spent": self._spent,
                    "budget": self._max_budget,
                    "action_cost": cost,
                },
            )

        self._spent += cost
        return PolicyResult(
            verdict=PolicyVerdict.ALLOW,
            rule_name=self.name,
            reason=(
                f"Risk budget OK: spent {self._spent}/{self._max_budget} "
                f"(+{cost} for this {risk_name} action)."
            ),
            metadata={
                "spent": self._spent,
                "budget": self._max_budget,
                "remaining": self.remaining_budget,
            },
        )


# ──────────────────────────────────────────────────────────────────────────────
# Policy Engine
# ──────────────────────────────────────────────────────────────────────────────

class PolicyEngine:
    """
    Composite policy evaluator for IronCore agent actions.

    Rules are evaluated in registration order.
    The first DENY verdict short-circuits the chain immediately.
    REQUIRE_SANDBOX is sticky: once any rule requests it, it propagates.

    Usage::

        engine = PolicyEngine.default()

        result = engine.evaluate(
            tool_name="shell_exec",
            args={"command": "ls /tmp"},
            context={"risk_level": "HIGH", "iteration": 3},
        )

        if not result.is_allowed:
            raise PermissionError(result.reason)
        if result.verdict == PolicyVerdict.REQUIRE_SANDBOX:
            action.requires_sandbox = True
    """

    def __init__(self) -> None:
        self._rules: List[BaseRule] = []
        self._lock = RLock()

    def add_rule(self, rule: BaseRule) -> "PolicyEngine":
        """
        Register a rule. Returns self for fluent chaining.

        Args:
            rule: Any BaseRule subclass instance.
        """
        with self._lock:
            self._rules.append(rule)
        logger.debug(f"[PolicyEngine] Rule registered: '{rule.name}'")
        return self

    def reload_rules(self, new_rules: List[BaseRule]) -> None:
        """
        Atomically replace the active rule chain.

        Args:
            new_rules: Fully constructed replacement rule chain.
        """
        validated_rules = list(new_rules)
        with self._lock:
            self._rules = validated_rules
        logger.info(
            "[PolicyEngine] Rule chain reloaded atomically | rule_count=%s",
            len(validated_rules),
        )

    def status(self) -> Dict[str, Any]:
        """Return a serializable snapshot of the active rule chain."""
        with self._lock:
            rules = [rule.name for rule in self._rules]
        return {
            "rule_count": len(rules),
            "rules": rules,
        }

    def evaluate(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        """
        Run all rules against the proposed action.

        Args:
            tool_name: Tool the agent wants to invoke.
            args:      Arguments to be passed to that tool.
            context:   Session context (iteration count, risk level, etc.).

        Returns:
            The final PolicyResult (DENY on first DENY; REQUIRE_SANDBOX
            if any rule requests it and none deny).
        """
        ctx = context or {}
        requires_sandbox = False
        with self._lock:
            rules = list(self._rules)

        for rule in rules:
            result = rule.evaluate(tool_name, args, ctx)

            if result.verdict == PolicyVerdict.DENY:
                logger.warning(
                    f"[PolicyEngine] DENIED '{tool_name}' by rule "
                    f"'{rule.name}': {result.reason}"
                )
                return result

            if result.verdict == PolicyVerdict.REQUIRE_SANDBOX:
                requires_sandbox = True

        verdict = (
            PolicyVerdict.REQUIRE_SANDBOX if requires_sandbox else PolicyVerdict.ALLOW
        )
        final = PolicyResult(
            verdict=verdict,
            rule_name="policy_engine",
            reason=(
                "All rules passed."
                + (" Sandbox execution required." if requires_sandbox else "")
            ),
        )
        logger.debug(
            f"[PolicyEngine] '{tool_name}' → {verdict.name}"
        )
        return final

    @classmethod
    def default(
        cls,
        allowed_tools: Optional[Set[str]] = None,
        sandboxed_tools: Optional[Set[str]] = None,
    ) -> "PolicyEngine":
        """
        Build the recommended production policy configuration.

        Rules applied (in order):
          1. DangerousArgPatternRule  – blocks injection patterns
          2. DenylistRule             – blocks known dangerous tools
          3. RateLimitRule            – throttles expensive tools
          4. SandboxEscalationRule    – escalates risky tools to Docker
          5. CumulativeRiskBudgetRule – session-level risk cap
          6. AllowlistRule            – (if provided) restrict tool surface

        Args:
            allowed_tools:   Optional set of permitted tool names.
            sandboxed_tools: Tools that must always run in a container.
        """
        engine = cls()

        engine.add_rule(DangerousArgPatternRule())

        engine.add_rule(DenylistRule(denied_tools={
            "raw_shell",
            "eval_python",
            "write_arbitrary_file",
        }))

        engine.add_rule(RateLimitRule(limits={
            "web_search":  (20, 60.0),
            "browser_open": (10, 60.0),
            "send_email":   (5, 300.0),
        }))

        effective_sandboxed = sandboxed_tools or {
            "run_python_script",
            "run_bash_script",
            "install_package",
        }
        engine.add_rule(SandboxEscalationRule(sandboxed_tools=effective_sandboxed))

        engine.add_rule(CumulativeRiskBudgetRule(max_budget=150))

        if allowed_tools is not None:
            engine.add_rule(AllowlistRule(allowed_tools=allowed_tools))

        logger.info(
            f"[PolicyEngine] Default configuration loaded — "
            f"{engine.status()['rule_count']} rules active."
        )
        return engine


# ──────────────────────────────────────────────────────────────────────────────
# Demo entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    policy = PolicyEngine.default(
        sandboxed_tools={"run_python_script", "run_bash_script"},
    )

    test_cases = [
        ("think",            {"thought": "Analyzing the problem..."},        "LOW"),
        ("run_python_script",{"code": "print('hello')"},                     "MEDIUM"),
        ("run_python_script",{"code": "import subprocess; subprocess.run([])"}, "HIGH"),
        ("raw_shell",        {"command": "rm -rf /"},                        "CRITICAL"),
        ("web_search",       {"query": "latest AI news"},                    "LOW"),
    ]

    print("\n── Policy Evaluation Tests ──")
    for tool, args, risk in test_cases:
        r = policy.evaluate(tool, args, context={"risk_level": risk})
        status = "✓ ALLOW" if r.verdict == PolicyVerdict.ALLOW else \
                 "⚠ SANDBOX" if r.verdict == PolicyVerdict.REQUIRE_SANDBOX else \
                 "✗ DENY"
        print(f"  {status:12} | {tool:25} | {r.reason[:70]}")
