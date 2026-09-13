"""
IronCore Standalone MCP Server (MCP 2.x Compliant)
Exposes IronCore Engine tools (DLP, Guardrails, Mouse Engine, CAPTCHA Mapper)
over standard Model Context Protocol (STDIO).
"""
import sys
import os
import asyncio
from pathlib import Path

# Ensure ironcore root directory is dynamically on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
os.environ["IRONCORE_EDITION"] = "enterprise"

from mcp.server.mcpserver import MCPServer
from ironcore.enterprise.dlp.engine import DLPEngine
from ironcore.enterprise.guardrail.rules_store import GuardrailRulesStore, GuardrailRule, GuardrailConditionType, GuardrailRemedy
from ironcore.enterprise.guardrail.evaluator import GuardrailEvaluator
from ironcore.browser.mouse_engine import BezierCurve, fitts_time, generate_control_points
from ironcore.browser.captcha_solver import TileCoordinateMapper

server = MCPServer("IronCore Enterprise Engine")

# 1. DLP Scan Tool
dlp_engine = DLPEngine()

@server.tool()
def dlp_scan_and_mask(text: str) -> dict:
    """Scan text for sensitive data (API keys, credit cards, PII) and return masked and tokenized text."""
    masked = dlp_engine.mask(text)
    tokenized, token_map = dlp_engine.tokenize(text)
    return {
        "original_length": len(text),
        "masked_text": masked,
        "tokenized_text": tokenized,
        "token_map": token_map
    }

# 2. Guardrail Jailbreak Check Tool
guard_store = GuardrailRulesStore(db_path=Path("/tmp/mcp_guardrail.db"))
guard_evaluator = GuardrailEvaluator(guard_store)

@server.tool()
async def guardrail_evaluate_prompt(prompt: str) -> dict:
    """Evaluate a user prompt against security guardrails and jailbreak rules."""
    await guard_store.initialize()
    res = await guard_evaluator.evaluate_input(prompt, session_id="mcp_session")
    return {
        "blocked": res.blocked,
        "reason": res.block_reason or "Clean / Passed",
        "violations_count": len(res.violations)
    }

# 3. Biometric Mouse Path Calculator Tool
@server.tool()
def calculate_biometric_mouse_path(start_x: float, start_y: float, target_x: float, target_y: float, points_count: int = 30) -> dict:
    """Calculate human-like mouse movement coordinates using Cubic Bezier Curve and Fitts Law."""
    p0 = (start_x, start_y)
    p3 = (target_x, target_y)
    p1, p2 = generate_control_points(p0, p3)
    curve = BezierCurve(p0, p1, p2, p3)
    trajectory = curve.generate_points(points_count)
    dist = ((target_x - start_x)**2 + (target_y - start_y)**2)**0.5
    duration_ms = fitts_time(dist, 20.0)
    return {
        "distance_px": round(dist, 2),
        "estimated_duration_ms": round(duration_ms, 2),
        "points": [{"x": round(x, 1), "y": round(y, 1)} for x, y in trajectory]
    }

# 4. CAPTCHA Tile Coordinates Tool
@server.tool()
def get_captcha_tile_coordinate(tile_index: int, iframe_x: float, iframe_y: float, iframe_w: float, iframe_h: float, grid_size: int = 3) -> dict:
    """Get absolute (X, Y) click target coordinate for an N x N CAPTCHA grid image."""
    center = TileCoordinateMapper.get_tile_center(
        tile_index=tile_index,
        iframe_rect={"x": iframe_x, "y": iframe_y, "width": iframe_w, "height": iframe_h},
        grid_size=grid_size
    )
    return {
        "tile_index": tile_index,
        "center_x": center[0],
        "center_y": center[1]
    }

# 5. Enterprise Cost & Budget Calculator
from ironcore.enterprise.budget.ledger import calculate_cost, ModelTier

@server.tool()
def calculate_llm_cost_and_savings(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0
) -> dict:
    """Compute exact USD cost, Anthropic cache savings, and tier rating for an LLM call."""
    cost, savings, tier = calculate_cost(
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_read_tokens=cache_read_tokens,
    )
    return {
        "model_id": model_id,
        "total_cost_usd": round(cost, 6),
        "cache_savings_usd": round(savings, 6),
        "model_tier": tier.value if hasattr(tier, "value") else str(tier)
    }

# 6. Airgap Network CIDR Guard
from ironcore.enterprise.airgap.config import AirGapConfig

@server.tool()
def airgap_verify_destination(host_or_ip: str) -> dict:
    """Verify if target IP / host is compliant with AirGap network isolation allowlist."""
    import ipaddress
    import socket
    config = AirGapConfig.from_env()
    allowed_cidrs = [ipaddress.ip_network(cidr) for cidr in config.allowed_internal_cidrs]
    
    is_allowed = False
    resolved_ip = host_or_ip
    try:
        ip_obj = ipaddress.ip_address(host_or_ip)
    except ValueError:
        try:
            resolved_ip = socket.gethostbyname(host_or_ip)
            ip_obj = ipaddress.ip_address(resolved_ip)
        except Exception as exc:
            return {"destination": host_or_ip, "allowed": False, "error": f"DNS resolution failed: {exc}"}
            
    for net in allowed_cidrs:
        if ip_obj in net:
            is_allowed = True
            break
            
    return {
        "destination": host_or_ip,
        "resolved_ip": resolved_ip,
        "allowed": is_allowed,
        "enforced_cidrs": [str(c) for c in allowed_cidrs]
    }

# 7. HITL Maker-Checker Ticket Creator
from ironcore.enterprise.hitl.engine import MakerCheckerEngine

hitl_engine = MakerCheckerEngine()

@server.tool()
async def hitl_submit_action(action_type: str, details: str, requester: str = "agent") -> dict:
    """Submit a high-risk enterprise action for human-in-the-loop (HITL) maker-checker approval."""
    ticket = await hitl_engine.request_approval(
        session_id=f"mcp_{requester}",
        action_type=action_type,
        action_payload={"details": details},
        risk_reason=f"Action '{action_type}' submitted via MCP by '{requester}'",
        approver_ids=["security-team@corp.com"],
    )
    return {
        "ticket_id": ticket.ticket_id,
        "action_type": ticket.action_type,
        "status": ticket.status.value,
        "created_at": ticket.created_at,
        "expires_at": ticket.expires_at
    }

# 8. Self-Healing Code AST Diagnosis
import ast

@server.tool()
def diagnose_python_code_ast(code: str, filename: str = "script.py") -> dict:
    """Parse and validate Python code AST to identify syntax errors, missing symbols, and structure."""
    try:
        tree = ast.parse(code, filename=filename)
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        return {
            "valid_syntax": True,
            "error": None,
            "classes_found": classes,
            "functions_found": functions,
            "node_count": len(list(ast.walk(tree)))
        }
    except SyntaxError as e:
        return {
            "valid_syntax": False,
            "error": f"{e.msg} at line {e.lineno}, col {e.offset}",
            "lineno": e.lineno,
            "offset": e.offset,
            "text": e.text
        }

# 9. Stealth Browser Defense Scripts
@server.tool()
def get_stealth_defense_scripts(defense_names: list[str] | None = None) -> dict:
    """Retrieve anti-fingerprinting JS injection payloads (canvas noise, webgl spoofer, audio defense, battery)."""
    scripts_dir = Path(__file__).resolve().parent / "ironcore" / "browser" / "fingerprint_defense"
    available = {}
    if scripts_dir.exists():
        for f in scripts_dir.glob("*.js"):
            if defense_names is None or f.stem in defense_names:
                available[f.name] = f.read_text(encoding="utf-8")[:500] + "... [truncated]"
    return {
        "scripts_count": len(available),
        "scripts": available
    }

if __name__ == "__main__":
    server.run(transport="stdio")

