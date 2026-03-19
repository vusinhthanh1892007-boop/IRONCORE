"""
Utilities for running deterministic rule scenarios during development and tests.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ironcore.security.policy_engine import BaseRule, PolicyVerdict


class RuleScenario(BaseModel):
    """Single rule evaluation scenario."""

    tool_name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    expected_verdict: PolicyVerdict


class ScenarioOutcome(BaseModel):
    """Outcome for one executed scenario."""

    tool_name: str
    expected_verdict: PolicyVerdict
    actual_verdict: PolicyVerdict
    passed: bool
    reason: str


class TestReport(BaseModel):
    """Aggregate report for a batch of rule scenarios."""

    rule_name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    outcomes: List[ScenarioOutcome] = Field(default_factory=list)


class RuleTester:
    """Run a rule against multiple scenarios and summarize the result."""

    @staticmethod
    def run_scenario(
        rule: BaseRule,
        scenarios: List[RuleScenario],
    ) -> TestReport:
        outcomes: List[ScenarioOutcome] = []
        for scenario in scenarios:
            result = rule.evaluate(
                tool_name=scenario.tool_name,
                args=scenario.args,
                context=scenario.context,
            )
            passed = result.verdict == scenario.expected_verdict
            outcomes.append(
                ScenarioOutcome(
                    tool_name=scenario.tool_name,
                    expected_verdict=scenario.expected_verdict,
                    actual_verdict=result.verdict,
                    passed=passed,
                    reason=result.reason,
                )
            )

        passed_count = sum(1 for outcome in outcomes if outcome.passed)
        return TestReport(
            rule_name=rule.name,
            total=len(outcomes),
            passed=passed_count,
            failed=len(outcomes) - passed_count,
            outcomes=outcomes,
        )
