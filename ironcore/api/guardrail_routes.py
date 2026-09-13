"""
Guardrail Studio API Routes — Phase 3, Security V3.

Endpoints consumed by ChatGPT UI V3 (Guardrail Studio panel):

  GET    /api/guardrail/rules                  → list all rules
  POST   /api/guardrail/rules                  → create rule
  GET    /api/guardrail/rules/{id}             → get one rule
  PUT    /api/guardrail/rules/{id}             → update rule
  DELETE /api/guardrail/rules/{id}             → delete rule
  POST   /api/guardrail/rules/{id}/enable      → toggle enabled
  POST   /api/guardrail/rules/{id}/test        → dry-run test
  POST   /api/guardrail/evaluate/input         → evaluate text as input
  POST   /api/guardrail/evaluate/output        → evaluate text as output
  GET    /api/guardrail/stats                  → aggregate stats

Author: Claude Security Engineer V3
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ironcore.enterprise.guardrail.evaluator import EvaluationResult, GuardrailEvaluator
from ironcore.enterprise.guardrail.rules_store import (
    GuardrailCategory,
    GuardrailConditionType,
    GuardrailRemedy,
    GuardrailRule,
    GuardrailRulesStore,
    GuardrailScope,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Guardrail"])

# Module-level singletons — inject via set_guardrail()
_store: Optional[GuardrailRulesStore] = None
_evaluator: Optional[GuardrailEvaluator] = None


def set_guardrail(store: GuardrailRulesStore) -> None:
    """Called at server startup to inject the shared GuardrailRulesStore."""
    global _store, _evaluator
    _store = store
    _evaluator = GuardrailEvaluator(store)
    logger.info("[GuardrailRoutes] GuardrailRulesStore registered.")


def _get_store() -> GuardrailRulesStore:
    if _store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Guardrail not initialized")
    return _store


def _get_evaluator() -> GuardrailEvaluator:
    if _evaluator is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Guardrail not initialized")
    return _evaluator


# ── Request / Response models ─────────────────────────────────────────────────

class CreateRuleRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "custom"
    scope: str = "both"
    condition_type: str = "keyword"
    condition_params: Dict[str, Any] = {}
    remedy: str = "warn"
    remedy_text: str = ""
    enabled: bool = True
    priority: int = 100


class UpdateRuleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    scope: Optional[str] = None
    condition_type: Optional[str] = None
    condition_params: Optional[Dict[str, Any]] = None
    remedy: Optional[str] = None
    remedy_text: Optional[str] = None
    priority: Optional[int] = None


class EnableRuleRequest(BaseModel):
    enabled: bool


class TestRuleRequest(BaseModel):
    text: str


class EvaluateRequest(BaseModel):
    text: str
    session_id: str = "api-test"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    category: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    enabled_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    """List guardrail rules with optional filters."""
    store = _get_store()
    rules = await store.list_rules(
        category=category,
        scope=scope,
        enabled_only=enabled_only,
        limit=limit,
        offset=offset,
    )
    return [r.model_dump() for r in rules]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(body: CreateRuleRequest) -> Dict[str, Any]:
    """Create a new guardrail policy rule."""
    store = _get_store()
    try:
        rule = GuardrailRule(
            name=body.name,
            description=body.description,
            category=GuardrailCategory(body.category),
            scope=GuardrailScope(body.scope),
            condition_type=GuardrailConditionType(body.condition_type),
            condition_params=body.condition_params,
            remedy=GuardrailRemedy(body.remedy),
            remedy_text=body.remedy_text,
            enabled=body.enabled,
            priority=body.priority,
        )
        saved = await store.add_rule(rule)
        return saved.model_dump()
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str) -> Dict[str, Any]:
    """Get a single rule by id."""
    store = _get_store()
    rule = await store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")
    return rule.model_dump()


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, body: UpdateRuleRequest) -> Dict[str, Any]:
    """Update an existing rule (partial update)."""
    store = _get_store()
    existing = await store.get_rule(rule_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")

    updates: Dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.category is not None:
        updates["category"] = GuardrailCategory(body.category)
    if body.scope is not None:
        updates["scope"] = GuardrailScope(body.scope)
    if body.condition_type is not None:
        updates["condition_type"] = GuardrailConditionType(body.condition_type)
    if body.condition_params is not None:
        updates["condition_params"] = body.condition_params
    if body.remedy is not None:
        updates["remedy"] = GuardrailRemedy(body.remedy)
    if body.remedy_text is not None:
        updates["remedy_text"] = body.remedy_text
    if body.priority is not None:
        updates["priority"] = body.priority

    updated = existing.model_copy(update=updates)
    try:
        saved = await store.add_rule(updated)
        return saved.model_dump()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str) -> None:
    """Delete a rule."""
    store = _get_store()
    deleted = await store.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")


@router.post("/rules/{rule_id}/enable")
async def toggle_rule(rule_id: str, body: EnableRuleRequest) -> Dict[str, Any]:
    """Enable or disable a rule."""
    store = _get_store()
    ok = await store.enable_rule(rule_id, body.enabled)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")
    return {"rule_id": rule_id, "enabled": body.enabled}


@router.post("/rules/{rule_id}/test")
async def test_rule(rule_id: str, body: TestRuleRequest) -> Dict[str, Any]:
    """Dry-run test a rule against provided text (no stats updated)."""
    store = _get_store()
    evaluator = _get_evaluator()
    rule = await store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not found")
    return await evaluator.test_rule(rule, body.text)


@router.post("/evaluate/input")
async def evaluate_input(body: EvaluateRequest) -> Dict[str, Any]:
    """Run the full input guardrail pipeline against the provided text."""
    evaluator = _get_evaluator()
    result: EvaluationResult = await evaluator.evaluate_input(body.text, session_id=body.session_id)
    return result.to_summary()


@router.post("/evaluate/output")
async def evaluate_output(body: EvaluateRequest) -> Dict[str, Any]:
    """Run the full output guardrail pipeline against the provided text."""
    evaluator = _get_evaluator()
    result: EvaluationResult = await evaluator.evaluate_output(body.text, session_id=body.session_id)
    return result.to_summary()


@router.get("/stats")
async def get_guardrail_stats() -> Dict[str, Any]:
    """Return aggregate Guardrail stats across all rules."""
    store = _get_store()
    all_rules = await store.list_rules(limit=10_000)

    total_rules = len(all_rules)
    enabled_rules = sum(1 for r in all_rules if r.enabled)
    total_evaluations = sum(r.total_evaluations for r in all_rules)
    total_violations = sum(r.total_violations for r in all_rules)

    # Top violating rules
    top_rules = sorted(all_rules, key=lambda r: r.total_violations, reverse=True)[:5]

    # Rule count by category
    category_counts: Dict[str, int] = {}
    for r in all_rules:
        category_counts[r.category.value] = category_counts.get(r.category.value, 0) + 1

    return {
        "total_rules": total_rules,
        "enabled_rules": enabled_rules,
        "disabled_rules": total_rules - enabled_rules,
        "total_evaluations": total_evaluations,
        "total_violations": total_violations,
        "violation_rate": round(total_violations / total_evaluations, 4) if total_evaluations else 0,
        "category_counts": category_counts,
        "top_violating_rules": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "violations": r.total_violations,
                "evaluations": r.total_evaluations,
            }
            for r in top_rules
        ],
    }
