"""
Tests — Phase 5: Security V3 — SIEM, IAM, Airgap & HITL API Routes.

Coverage:
  1.  siem: record_event adds to ring buffer
  2.  siem: list_siem_events returns events, newest first
  3.  siem: siem_stats aggregates severity counts correctly
  4.  siem: siem_config returns transport env vars
  5.  siem: siem_test_event adds event to ring buffer
  6.  iam: list_roles returns default roles
  7.  iam: create_role adds new role
  8.  iam: delete_role fails if role has members
  9.  iam: get_sso_config returns masked secrets
  10. iam: get_vault_bindings does not expose secret values
  11. airgap: airgap_status returns expected keys
  12. airgap: record_violation logs to ring buffer
  13. airgap: update_airgap_config sets env vars
  14. hitl: approve_hitl transitions to next level (multi-level)
  15. hitl: reject_hitl marks status rejected + audit entry
"""

from __future__ import annotations

import time
import os
from typing import Dict, Any

import pytest

# ── Force non-enterprise mode check (SIEM module checks edition) ────────────
os.environ.setdefault("IRONCORE_EDITION", "enterprise")


# ── Test 1: record_event adds to ring buffer ─────────────────────────────────

def test_siem_record_event():
    import importlib
    import ironcore.api.siem_routes as sr
    importlib.reload(sr)
    sr.record_event({"event_type": "firewall_block", "severity": "high", "session_id": "s1"})
    assert len(sr._event_log) >= 1
    ev = list(sr._event_log)[-1]
    assert ev["event_type"] == "firewall_block"
    assert ev["severity"] == "high"


# ── Test 2: list_siem_events returns newest first ────────────────────────────

async def test_siem_list_events_newest_first():
    import ironcore.api.siem_routes as sr
    sr._event_log.clear()
    sr.record_event({"event_type": "ev_old", "severity": "low", "timestamp": time.time() - 100})
    sr.record_event({"event_type": "ev_new", "severity": "high", "timestamp": time.time()})
    result = await sr.list_siem_events(limit=10, offset=0, severity=None, event_type=None)
    assert result["events"][0]["event_type"] == "ev_new"      # newest first
    assert result["total"] >= 2


# ── Test 3: siem_stats severity aggregation ──────────────────────────────────

async def test_siem_stats_aggregation():
    import ironcore.api.siem_routes as sr
    sr._event_log.clear()
    sr.record_event({"event_type": "t1", "severity": "critical"})
    sr.record_event({"event_type": "t2", "severity": "critical"})
    sr.record_event({"event_type": "t3", "severity": "low"})
    stats = await sr.siem_stats()
    assert stats["severity_counts"]["critical"] == 2
    assert stats["severity_counts"]["low"] == 1
    assert stats["total_events"] == 3


# ── Test 4: siem_config returns env-based values ─────────────────────────────

async def test_siem_config():
    import ironcore.api.siem_routes as sr
    os.environ["IRONCORE_SIEM_TRANSPORTS"] = "splunk,syslog"
    config = await sr.siem_config()
    assert "splunk" in config["transports"]
    assert "syslog" in config["transports"]
    assert "buffer_size" in config


# ── Test 5: siem test event ──────────────────────────────────────────────────

async def test_siem_test_event():
    import ironcore.api.siem_routes as sr
    from ironcore.api.siem_routes import TestEventRequest
    req = TestEventRequest(event_type="auth_success", severity="low", session_id="abc")
    result = await sr.siem_test_event(req)
    assert result["status"] == "ok"
    assert "event_id" in result
    assert result["ring_buffer_size"] >= 1


# ── Test 6: list_roles returns defaults ──────────────────────────────────────

async def test_iam_list_roles():
    import ironcore.api.iam_routes as ir
    roles = await ir.list_roles()
    role_ids = {r["id"] for r in roles}
    assert "admin" in role_ids
    assert "viewer" in role_ids


# ── Test 7: create_role adds new role ────────────────────────────────────────

async def test_iam_create_role():
    import ironcore.api.iam_routes as ir
    from ironcore.api.iam_routes import CreateRoleRequest
    # Remove if exists from previous run
    ir._roles.pop("security_reviewer", None)
    body = CreateRoleRequest(name="Security Reviewer", permissions=["siem:view", "hitl:view"])
    role = await ir.create_role(body)
    assert role["id"] == "security_reviewer"
    assert "siem:view" in role["permissions"]


# ── Test 8: delete_role fails if has members ─────────────────────────────────

async def test_iam_delete_role_with_members():
    import ironcore.api.iam_routes as ir
    ir._roles["test_role_with_member"] = {
        "id": "test_role_with_member",
        "name": "Test",
        "permissions": [],
        "description": "",
        "created_at": time.time(),
        "members": ["user@test.com"],
    }
    with pytest.raises(Exception) as exc_info:
        await ir.delete_role("test_role_with_member")
    assert "409" in str(exc_info.value) or "member" in str(exc_info.value).lower()
    # Cleanup
    ir._roles.pop("test_role_with_member", None)


# ── Test 9: get_sso_config masks secrets ─────────────────────────────────────

async def test_iam_sso_config_masked():
    import ironcore.api.iam_routes as ir
    os.environ["IRONCORE_SSO_CLIENT_SECRET"] = "supersecret123"
    config = await ir.get_sso_config()
    assert config["client_secret"] == "****"
    assert "supersecret123" not in str(config)


# ── Test 10: vault bindings has no secret values ─────────────────────────────

async def test_iam_vault_bindings_no_values():
    import ironcore.api.iam_routes as ir
    bindings = await ir.get_vault_bindings()
    assert len(bindings) >= 1
    for binding in bindings:
        assert "value" not in binding
        assert "secret" not in binding
        assert "password" not in binding


# ── Test 11: airgap status returns expected keys ─────────────────────────────

async def test_airgap_status_keys():
    import ironcore.api.airgap_routes as ar
    result = await ar.airgap_status()
    assert "airgap_enabled" in result
    assert "allowed_internal_cidrs" in result
    assert "violation_count_total" in result
    assert isinstance(result["allowed_internal_cidrs"], list)


# ── Test 12: record_violation logs to SQLite ────────────────────────────

def test_airgap_record_violation():
    import ironcore.api.airgap_routes as ar
    before = ar._total_violations()
    ar.record_violation("evil.external.com", "session-xyz", "blocked by airgap test")
    assert ar._total_violations() == before + 1
    last = ar._load_violations(limit=1)[0]
    assert last["host"] == "evil.external.com"
    assert last["session_id"] == "session-xyz"


# ── Test 13: update_airgap_config sets env vars ──────────────────────────────

async def test_airgap_update_config():
    import ironcore.api.airgap_routes as ar
    from ironcore.api.airgap_routes import UpdateAirgapConfigRequest
    body = UpdateAirgapConfigRequest(
        allow_external_network=False,
        allowed_internal_cidrs=["10.0.0.0/8", "172.16.0.0/12"],
    )
    result = await ar.update_airgap_config(body)
    assert result["status"] == "updated"
    assert os.environ.get("IRONCORE_AIRGAP_ALLOW_EXTERNAL") == "false"
    assert "10.0.0.0/8" in os.environ.get("IRONCORE_AIRGAP_ALLOWED_CIDRS", "")


# ── Test 14: approve_hitl multi-level escalation ─────────────────────────────

async def test_hitl_approve_multi_level():
    import ironcore.api.hitl_routes as hr
    from ironcore.api.hitl_routes import ApproveRequest
    req_id = "test-req-multilevel"
    hr._requests[req_id] = {
        "id": req_id,
        "action_type": "critical_delete",
        "risk_level": "high",
        "current_level": 1,
        "approval_chain": [
            {"level": 1, "role_required": "team_lead", "timeout_minutes": 5, "auto_action_on_timeout": "escalate"},
            {"level": 2, "role_required": "manager", "timeout_minutes": 10, "auto_action_on_timeout": "reject"},
        ],
        "decisions": [],
        "status": "pending_l1",
        "created_at": time.time(),
        "sla_expires_at": time.time() + 300,
    }
    result = await hr.approve_hitl(req_id, ApproveRequest(approver_id="alice", reason="Looks good"))
    # After L1 approval, should escalate to L2
    assert result["status"] == "pending_l2"
    assert hr._requests[req_id]["current_level"] == 2
    # Cleanup
    hr._requests.pop(req_id, None)


# ── Test 15: reject_hitl marks rejected + audit entry ────────────────────────

async def test_hitl_reject():
    import ironcore.api.hitl_routes as hr
    from ironcore.api.hitl_routes import RejectRequest
    req_id = "test-req-reject"
    hr._requests[req_id] = {
        "id": req_id,
        "action_type": "exec_shell",
        "risk_level": "critical",
        "current_level": 1,
        "approval_chain": [{"level": 1, "role_required": "admin", "timeout_minutes": 5, "auto_action_on_timeout": "reject"}],
        "decisions": [],
        "status": "pending_l1",
        "created_at": time.time(),
        "sla_expires_at": time.time() + 300,
    }
    result = await hr.reject_hitl(req_id, RejectRequest(reason="Too risky", rejector_id="bob"))
    assert result["status"] == "rejected"
    # Verify audit chain entry was created
    chain = hr._audit_chains.get(req_id, [])
    assert len(chain) >= 1
    assert chain[0]["action"] == "rejected"
    # Cleanup
    hr._requests.pop(req_id, None)
    hr._audit_chains.pop(req_id, None)
