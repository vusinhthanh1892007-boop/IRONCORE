import asyncio
from pathlib import Path

from ironcore.security.policy_engine import AllowlistRule, DenylistRule, PolicyEngine, PolicyVerdict
from ironcore.security.rbac import RBACRule, Role, issue_token, validate_token
from ironcore.security.rule_loader import RuleLoader
from ironcore.security.rule_tester import RuleScenario, RuleTester


def test_rbac_rule_uses_jwt_and_risk_permissions() -> None:
    secret = "phase-6-secret"
    rule = RBACRule(token_secret=secret)
    operator_token = issue_token(Role.OPERATOR, expires_in_seconds=60, secret=secret)

    low_result = rule.evaluate(
        tool_name="think",
        args={},
        context={"auth_token": operator_token, "risk_level": "LOW"},
    )
    assert low_result.verdict == PolicyVerdict.ALLOW
    assert low_result.metadata["role"] == Role.OPERATOR.value

    high_result = rule.evaluate(
        tool_name="run_python_script",
        args={},
        context={"auth_token": operator_token, "risk_level": "HIGH"},
    )
    assert high_result.verdict == PolicyVerdict.DENY
    assert "dispatch_high" in high_result.reason


def test_validate_token_rejects_tampering() -> None:
    secret = "phase-6-secret"
    token = issue_token(Role.ADMIN, expires_in_seconds=60, secret=secret)
    tampered = f"{token[:-1]}x"

    assert validate_token(token, secret=secret) == Role.ADMIN
    assert validate_token(tampered, secret=secret) is None


def test_policy_engine_reload_rules_swaps_chain_atomically() -> None:
    engine = PolicyEngine()
    engine.add_rule(AllowlistRule({"think"}))

    denied_before = engine.evaluate("finish", args={})
    assert denied_before.verdict == PolicyVerdict.DENY

    engine.reload_rules([AllowlistRule({"finish"})])
    allowed_after = engine.evaluate("finish", args={})
    assert allowed_after.verdict == PolicyVerdict.ALLOW
    assert engine.status()["rules"] == ["allowlist"]


def test_rule_loader_loads_rules_from_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "policy.toml"
    config_path.write_text(
        """
        [[rules]]
        type = "denylist"
        denied_tools = ["raw_shell"]

        [[rules]]
        type = "rbac"
        tool_permissions = { rotate_secret = "manage_secrets" }
        read_only_tools = ["history_read"]
        token_secret = "phase-6-secret"
        """,
        encoding="utf-8",
    )

    rules = RuleLoader.load_from_toml(config_path)

    assert [rule.name for rule in rules] == ["denylist", "rbac"]


def test_rule_tester_builds_summary_report() -> None:
    report = RuleTester.run_scenario(
        rule=DenylistRule({"raw_shell"}),
        scenarios=[
            RuleScenario(
                tool_name="raw_shell",
                args={},
                context={},
                expected_verdict=PolicyVerdict.DENY,
            ),
            RuleScenario(
                tool_name="think",
                args={},
                context={},
                expected_verdict=PolicyVerdict.ALLOW,
            ),
        ],
    )

    assert report.rule_name == "denylist"
    assert report.total == 2
    assert report.passed == 2
    assert report.failed == 0


def test_rule_loader_watch_hot_reloads_policy(tmp_path: Path) -> None:
    async def scenario() -> None:
        config_path = tmp_path / "policy.toml"
        config_path.write_text(
            """
            [[rules]]
            type = "allowlist"
            allowed_tools = ["think"]
            """,
            encoding="utf-8",
        )

        engine = PolicyEngine()
        loader = RuleLoader(engine, poll_interval_seconds=0.05)
        await loader.reload_from_file(config_path)

        initial_result = engine.evaluate("finish", args={})
        assert initial_result.verdict == PolicyVerdict.DENY

        stop_event = asyncio.Event()
        watch_task = asyncio.create_task(loader.watch(config_path, stop_event=stop_event))
        try:
            await asyncio.sleep(0.1)
            config_path.write_text(
                """
                [[rules]]
                type = "allowlist"
                allowed_tools = ["finish"]
                """,
                encoding="utf-8",
            )

            reloaded_result = None
            for _ in range(20):
                await asyncio.sleep(0.05)
                reloaded_result = engine.evaluate("finish", args={})
                if reloaded_result.verdict == PolicyVerdict.ALLOW:
                    break

            assert reloaded_result is not None
            assert reloaded_result.verdict == PolicyVerdict.ALLOW
        finally:
            stop_event.set()
            await watch_task

    asyncio.run(scenario())
