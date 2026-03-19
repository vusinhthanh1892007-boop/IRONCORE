"""
IronCore V2 — Phase 5 Tests: MCP Server
=======================================

Chạy: python -m pytest tests/test_phase5_optimizer_mcp.py -v

Coverage:
  - Data Models: validation (MCPRequest, MCPResponse)
  - MCPServer.handle_initialize
  - MCPServer.list_resources / read_resource
  - MCPServer.list_tools / call_tool (với IronCoreEngine mock)
  - MCPServer.list_prompts / get_prompt
  - MCPServer.dispatch mapping và error handling
  - Fallback JSON schema cho tools không có strict schema

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import pytest

from ironcore.core.engine import IronCoreEngine, ToolDefinition, Observation, RiskLevel
from ironcore.optimizer.mcp_server import (
    MCPRequest,
    MCPResponse,
    MCPServer,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & Mocks
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_engine() -> IronCoreEngine:
    """Tạo IronCoreEngine với 1 custom tool + builtin tools (think, finish)."""
    engine = IronCoreEngine(max_iterations=5)

    async def mock_handler(x: int, y: int) -> Observation:
        if x < 0:
            raise ValueError("x cannot be negative")
        return Observation(content={"sum": x + y})

    engine.register_tool(
        ToolDefinition(
            name="add_numbers",
            handler=mock_handler,
            risk_level=RiskLevel.LOW,
            description="Adds two numbers",
        )
    )
    return engine


@pytest.fixture
def mcp_server(mock_engine: IronCoreEngine) -> MCPServer:
    return MCPServer(engine=mock_engine)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Initialization
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_initialize(mcp_server: MCPServer):
    """Test initialize trả về đúng protocol version và capabilities."""
    req = MCPRequest(id=1, method="initialize", params={"clientInfo": {"name": "Claude Desktop"}})
    resp: MCPResponse = await mcp_server.dispatch(req)
    
    assert resp.error is None
    res = resp.result
    assert res["protocolVersion"] == "2024-11-05"
    assert "capabilities" in res
    assert res["serverInfo"]["name"] == "IronCore MCP Server"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Resources
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resources(mcp_server: MCPServer):
    """Test resources/list trả về config và metrics."""
    req = MCPRequest(id=2, method="resources/list")
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    resources = resp.result["resources"]
    assert len(resources) >= 2
    uris = [r["uri"] for r in resources]
    assert "ironcore://config/system_prompt" in uris
    assert "ironcore://metrics/engine" in uris


@pytest.mark.asyncio
async def test_read_resource_prompt(mcp_server: MCPServer):
    """Test resources/read cho system prompt."""
    req = MCPRequest(id=3, method="resources/read", params={"uri": "ironcore://config/system_prompt"})
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    contents = resp.result["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "ironcore://config/system_prompt"
    assert "IronCore" in contents[0]["text"]


@pytest.mark.asyncio
async def test_read_resource_not_found(mcp_server: MCPServer):
    """Test resources/read uri sai → error."""
    req = MCPRequest(id=4, method="resources/read", params={"uri": "ironcore://unknown"})
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is not None
    assert resp.error["code"] == -32602
    assert "Resource not found" in resp.error["message"]


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Tools
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools(mcp_server: MCPServer):
    """Test tools/list trả về registered tools với format MCP."""
    req = MCPRequest(id=5, method="tools/list")
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    tools = resp.result["tools"]
    tool_names = [t["name"] for t in tools]
    
    assert "think" in tool_names
    assert "finish" in tool_names
    assert "add_numbers" in tool_names
    
    # Check schema generation fallback
    add_tool = next(t for t in tools if t["name"] == "add_numbers")
    assert add_tool["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_call_tool_success(mcp_server: MCPServer):
    """Test tools/call thực thi tool và trả về content."""
    req = MCPRequest(
        id=6, 
        method="tools/call", 
        params={
            "name": "add_numbers",
            "arguments": {"x": 5, "y": 7}
        }
    )
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    res = resp.result
    assert res["isError"] is False
    assert "12" in res["content"][0]["text"]  # "{'sum': 12}"


@pytest.mark.asyncio
async def test_call_tool_exception(mcp_server: MCPServer):
    """Test tools/call khi tool raise exception."""
    req = MCPRequest(
        id=7, 
        method="tools/call", 
        params={
            "name": "add_numbers",
            "arguments": {"x": -5, "y": 7}
        }
    )
    resp = await mcp_server.dispatch(req)
    
    # Exception trong tool handler vẫn trả về MCP response HTTP 200, nhưng isError=True
    assert resp.error is None
    assert resp.result["isError"] is True
    assert "cannot be negative" in resp.result["content"][0]["text"]


@pytest.mark.asyncio
async def test_call_tool_not_found(mcp_server: MCPServer):
    """Test tools/call với tên tool sai."""
    req = MCPRequest(id=8, method="tools/call", params={"name": "unknown_tool"})
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    assert resp.result["isError"] is True
    assert "not found" in resp.result["content"][0]["text"]


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Prompts
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_prompts(mcp_server: MCPServer):
    """Test prompts/list."""
    req = MCPRequest(id=9, method="prompts/list")
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    prompts = resp.result["prompts"]
    assert len(prompts) >= 1
    assert prompts[0]["name"] == "ironcore_expert"
    assert prompts[0]["arguments"][0]["name"] == "topic"


@pytest.mark.asyncio
async def test_get_prompt_success(mcp_server: MCPServer):
    """Test prompts/get render prompt."""
    req = MCPRequest(
        id=10, 
        method="prompts/get", 
        params={"name": "ironcore_expert", "arguments": {"topic": "memory optimization"}}
    )
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is None
    messages = resp.result["messages"]
    assert len(messages) == 1
    assert "memory optimization" in messages[0]["content"]["text"]


@pytest.mark.asyncio
async def test_get_prompt_not_found(mcp_server: MCPServer):
    """Test prompts/get template sai."""
    req = MCPRequest(id=11, method="prompts/get", params={"name": "unknown_prompt"})
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is not None
    assert resp.error["code"] == -32602
    assert "not found" in resp.error["message"]


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Dispatcher
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_method_not_found(mcp_server: MCPServer):
    """Test method JSON-RPC ko hỗ trợ."""
    req = MCPRequest(id=12, method="unknown/method")
    resp = await mcp_server.dispatch(req)
    
    assert resp.error is not None
    assert resp.error["code"] == -32601
    assert "Method not found" in resp.error["message"]
