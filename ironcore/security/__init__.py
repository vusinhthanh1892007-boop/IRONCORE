"""IronCore security subsystem exports."""

from ironcore.security.policy_engine import (
    AllowlistRule,
    BaseRule,
    CumulativeRiskBudgetRule,
    DangerousArgPatternRule,
    DenylistRule,
    PolicyEngine,
    PolicyResult,
    PolicyVerdict,
    RateLimitRule,
    SandboxEscalationRule,
)
from ironcore.security.rbac import Permission, RBACRule, ROLE_PERMISSIONS, Role, issue_token, validate_token
from ironcore.security.rule_loader import RuleLoader
from ironcore.security.rule_tester import RuleScenario, RuleTester, TestReport
from ironcore.security.secrets_vault import SecretsVault
from ironcore.security.prompt_scanner import (
    ThreatCategory,
    ScanAction,
    ScanResult,
    PromptScanner,
    INJECTION_PATTERNS,
    build_cef_event,
)

__all__ = [
    "AllowlistRule",
    "BaseRule",
    "CumulativeRiskBudgetRule",
    "DangerousArgPatternRule",
    "DenylistRule",
    "Permission",
    "PolicyEngine",
    "PolicyResult",
    "PolicyVerdict",
    "RBACRule",
    "ROLE_PERMISSIONS",
    "RateLimitRule",
    "Role",
    "RuleLoader",
    "RuleScenario",
    "RuleTester",
    "SandboxEscalationRule",
    "SecretsVault",
    "TestReport",
    "issue_token",
    "validate_token",
    # Phase 19 — Prompt Scanner
    "ThreatCategory",
    "ScanAction",
    "ScanResult",
    "PromptScanner",
    "INJECTION_PATTERNS",
    "build_cef_event",
]
