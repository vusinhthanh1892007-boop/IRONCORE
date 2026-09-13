"""
Tests — Phase 3: Security V3 — Guardrail Studio Backend.

Coverage:
  1.  store: add_rule persists correctly
  2.  store: get_rule returns correct fields
  3.  store: delete_rule removes entry
  4.  store: enable_rule toggles correctly
  5.  store: list_rules filters by enabled_only
  6.  store: increment_stats updates counters
  7.  store: rule validation errors reported
  8.  evaluator: KEYWORD rule blocks on match
  9.  evaluator: KEYWORD rule allows non-match
  10. evaluator: REGEX rule matches pattern
  11. evaluator: LENGTH rule blocks oversized text
  12. evaluator: REWRITE remedy modifies text
  13. evaluator: APPEND remedy appends text
  14. evaluator: BLOCK stops chain (subsequent rules skipped)
  15. evaluator: evaluate_output vs evaluate_input scope filtering
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

async def make_store(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailRulesStore
    db = tmp_path / "test_guardrail.db"
    store = GuardrailRulesStore(db_path=db)
    await store.initialize()
    return store


def make_rule(**kwargs):
    from ironcore.enterprise.guardrail.rules_store import (
        GuardrailRule, GuardrailCategory, GuardrailScope,
        GuardrailConditionType, GuardrailRemedy,
    )
    defaults = {
        "name": "Test Rule",
        "category": GuardrailCategory.CUSTOM,
        "scope": GuardrailScope.BOTH,
        "condition_type": GuardrailConditionType.KEYWORD,
        "condition_params": {"keywords": ["bad_word"]},
        "remedy": GuardrailRemedy.WARN,
    }
    defaults.update(kwargs)
    return GuardrailRule(**defaults)


# ── Test 1: add_rule persists ─────────────────────────────────────────────────

async def test_add_rule_persists(tmp_path: Path):
    store = await make_store(tmp_path)
    rule = make_rule(name="Rule A")
    saved = await store.add_rule(rule)
    assert saved.rule_id == rule.rule_id

    fetched = await store.get_rule(rule.rule_id)
    assert fetched is not None
    assert fetched.name == "Rule A"


# ── Test 2: get_rule fields correct ──────────────────────────────────────────

async def test_get_rule_fields_correct(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailScope, GuardrailRemedy
    store = await make_store(tmp_path)
    rule = make_rule(
        name="My Policy",
        scope=GuardrailScope.OUTPUT,
        remedy=GuardrailRemedy.BLOCK,
        condition_params={"keywords": ["forbidden"]},
        priority=10,
    )
    await store.add_rule(rule)
    fetched = await store.get_rule(rule.rule_id)
    assert fetched.scope.value == "output"
    assert fetched.remedy.value == "block"
    assert fetched.priority == 10
    assert "forbidden" in fetched.condition_params["keywords"]


# ── Test 3: delete_rule ───────────────────────────────────────────────────────

async def test_delete_rule(tmp_path: Path):
    store = await make_store(tmp_path)
    rule = make_rule()
    await store.add_rule(rule)
    deleted = await store.delete_rule(rule.rule_id)
    assert deleted is True
    assert await store.get_rule(rule.rule_id) is None

    # delete non-existent → False
    assert await store.delete_rule("nonexistent") is False


# ── Test 4: enable_rule toggles ──────────────────────────────────────────────

async def test_enable_rule_toggle(tmp_path: Path):
    store = await make_store(tmp_path)
    rule = make_rule()
    await store.add_rule(rule)
    await store.enable_rule(rule.rule_id, False)
    fetched = await store.get_rule(rule.rule_id)
    assert fetched.enabled is False
    await store.enable_rule(rule.rule_id, True)
    fetched2 = await store.get_rule(rule.rule_id)
    assert fetched2.enabled is True


# ── Test 5: list_rules enabled_only ──────────────────────────────────────────

async def test_list_rules_enabled_only(tmp_path: Path):
    store = await make_store(tmp_path)
    enabled_rule = make_rule(name="Enabled")
    disabled_rule = make_rule(name="Disabled", enabled=False)
    await store.add_rule(enabled_rule)
    await store.add_rule(disabled_rule)

    active = await store.list_rules(enabled_only=True)
    names = {r.name for r in active}
    assert "Enabled" in names
    assert "Disabled" not in names


# ── Test 6: increment_stats ───────────────────────────────────────────────────

async def test_increment_stats(tmp_path: Path):
    store = await make_store(tmp_path)
    rule = make_rule()
    await store.add_rule(rule)
    await store.increment_stats(rule.rule_id, violated=True)
    await store.increment_stats(rule.rule_id, violated=False)
    fetched = await store.get_rule(rule.rule_id)
    assert fetched.total_evaluations == 2
    assert fetched.total_violations == 1


# ── Test 7: rule validation errors ───────────────────────────────────────────

def test_rule_validation_errors():
    from ironcore.enterprise.guardrail.rules_store import GuardrailRule, GuardrailConditionType
    rule = GuardrailRule(
        name="",   # invalid — empty name
        condition_type=GuardrailConditionType.KEYWORD,
        condition_params={},  # invalid — no keywords
    )
    errors = rule.validate_fields()
    assert any("name" in e for e in errors)
    assert any("keywords" in e for e in errors)


# ── Test 8: KEYWORD rule blocks ───────────────────────────────────────────────

async def test_keyword_rule_blocks(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailRemedy, GuardrailScope
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    rule = make_rule(
        scope=GuardrailScope.INPUT,
        condition_params={"keywords": ["competitor"]},
        remedy=GuardrailRemedy.BLOCK,
    )
    await store.add_rule(rule)
    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_input("buy competitor product please")
    assert result.blocked is True
    assert result.has_violations is True


# ── Test 9: KEYWORD no match → allow ─────────────────────────────────────────

async def test_keyword_no_match_allows(tmp_path: Path):
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    rule = make_rule(condition_params={"keywords": ["xyz_special_block"]})
    await store.add_rule(rule)
    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_input("completely innocent text")
    assert result.blocked is False
    assert not result.has_violations


# ── Test 10: REGEX rule matches ───────────────────────────────────────────────

async def test_regex_rule_matches(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailConditionType, GuardrailRemedy
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    rule = make_rule(
        name="No SSN",
        condition_type=GuardrailConditionType.REGEX,
        condition_params={"pattern": r"\d{3}-\d{2}-\d{4}"},
        remedy=GuardrailRemedy.BLOCK,
    )
    await store.add_rule(rule)
    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_output("My SSN is 123-45-6789 please use it")
    assert result.blocked is True
    assert result.has_violations is True


# ── Test 11: LENGTH rule blocks oversized ─────────────────────────────────────

async def test_length_rule_blocks(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import (
        GuardrailConditionType, GuardrailRemedy, GuardrailScope,
    )
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    rule = make_rule(
        name="Max 20 chars",
        condition_type=GuardrailConditionType.LENGTH,
        condition_params={"max_chars": 20},
        scope=GuardrailScope.OUTPUT,
        remedy=GuardrailRemedy.WARN,
    )
    await store.add_rule(rule)
    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_output("A" * 25)
    assert result.has_violations is True
    assert result.violations[0].rule_id == rule.rule_id


# ── Test 12: REWRITE remedy modifies text ─────────────────────────────────────

async def test_rewrite_remedy(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailRemedy
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    rule = make_rule(
        condition_params={"keywords": ["bad_word"]},
        remedy=GuardrailRemedy.REWRITE,
        remedy_text="[FILTERED]",
    )
    await store.add_rule(rule)
    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_input("please use bad_word here")
    assert result.rewritten_text is not None
    assert "[FILTERED]" in result.rewritten_text
    assert "bad_word" not in result.rewritten_text


# ── Test 13: APPEND remedy adds text ─────────────────────────────────────────

async def test_append_remedy(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailRemedy, GuardrailScope
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    rule = make_rule(
        condition_params={"keywords": ["financial advice"]},
        remedy=GuardrailRemedy.APPEND,
        remedy_text="⚠️ Disclaimer: This is not financial advice.",
        scope=GuardrailScope.OUTPUT,
    )
    await store.add_rule(rule)
    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_output("Here is some financial advice for you.")
    assert result.rewritten_text is not None
    assert "Disclaimer" in result.rewritten_text


# ── Test 14: BLOCK stops chain ────────────────────────────────────────────────

async def test_block_stops_chain(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailRemedy
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)
    # Priority 10 = evaluated first, BLOCK
    block_rule = make_rule(
        name="Blocker",
        condition_params={"keywords": ["stop_here"]},
        remedy=GuardrailRemedy.BLOCK,
        priority=10,
    )
    # Priority 100 = evaluated second (but should never be reached)
    warn_rule = make_rule(
        name="Should not reach",
        condition_params={"keywords": ["stop_here"]},
        remedy=GuardrailRemedy.WARN,
        priority=100,
    )
    await store.add_rule(block_rule)
    await store.add_rule(warn_rule)

    eval_ = GuardrailEvaluator(store)
    result = await eval_.evaluate_input("stop_here please")

    assert result.blocked is True
    # Only one violation (chain stopped at BLOCK)
    assert len(result.violations) == 1
    assert result.violations[0].rule_id == block_rule.rule_id


# ── Test 15: scope filtering (input vs output) ────────────────────────────────

async def test_scope_filtering(tmp_path: Path):
    from ironcore.enterprise.guardrail.rules_store import GuardrailRemedy, GuardrailScope, GuardrailConditionType
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    store = await make_store(tmp_path)

    # INPUT-only rule
    input_rule = make_rule(
        name="Input Only",
        scope=GuardrailScope.INPUT,
        condition_params={"keywords": ["trigger_word"]},
        remedy=GuardrailRemedy.WARN,
    )
    # OUTPUT-only rule
    output_rule = make_rule(
        name="Output Only",
        scope=GuardrailScope.OUTPUT,
        condition_params={"keywords": ["trigger_word"]},
        remedy=GuardrailRemedy.WARN,
    )
    await store.add_rule(input_rule)
    await store.add_rule(output_rule)

    eval_ = GuardrailEvaluator(store)

    # evaluate_input should only trigger input_rule
    in_result = await eval_.evaluate_input("trigger_word here")
    triggered_ids = {v.rule_id for v in in_result.violations}
    assert input_rule.rule_id in triggered_ids
    assert output_rule.rule_id not in triggered_ids

    # evaluate_output should only trigger output_rule
    out_result = await eval_.evaluate_output("trigger_word here")
    triggered_ids2 = {v.rule_id for v in out_result.violations}
    assert output_rule.rule_id in triggered_ids2
    assert input_rule.rule_id not in triggered_ids2


# ── Test 16: LLM judge fail-closed policy (security default) ─────────────────

async def test_llm_judge_fail_closed_policy(tmp_path: Path):
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    from ironcore.enterprise.guardrail.rules_store import GuardrailConditionType, GuardrailRemedy

    store = await make_store(tmp_path)
    llm_rule = make_rule(
        name="LLM Jailbreak Guard",
        condition_type=GuardrailConditionType.LLM,
        condition_params={"judge_prompt": "Check safety", "fail_closed": True},
        remedy=GuardrailRemedy.BLOCK,
    )
    await store.add_rule(llm_rule)
    eval_ = GuardrailEvaluator(store)

    # When LLM bridge is unavailable or throws, fail-closed must block
    result = await eval_.evaluate_input("Potentially adversarial prompt")
    assert result.blocked is True
    assert any("fail-closed policy enforced" in v.evidence for v in result.violations)


# ── Test 17: LLM judge fail-open policy when explicitly configured ───────────

async def test_llm_judge_fail_open_policy(tmp_path: Path):
    from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
    from ironcore.enterprise.guardrail.rules_store import GuardrailConditionType, GuardrailRemedy

    store = await make_store(tmp_path)
    llm_rule = make_rule(
        name="LLM Non-critical Scan",
        condition_type=GuardrailConditionType.LLM,
        condition_params={"judge_prompt": "Check tone", "fail_closed": False},
        remedy=GuardrailRemedy.BLOCK,
    )
    await store.add_rule(llm_rule)
    eval_ = GuardrailEvaluator(store)

    # When LLM bridge fails with fail_closed=False, request is permitted
    result = await eval_.evaluate_input("Regular text")
    assert result.blocked is False

