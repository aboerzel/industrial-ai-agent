"""Integration boundary coverage for Agent API operational readiness."""

import asyncio

import pytest

from industrial_ai_agent.infrastructure.agent_api_readiness import (
    AgentApiReadinessError,
    RequiredMcpService,
    check_required_mcp_services,
)
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
)


def test_readiness_recovers_when_a_required_mcp_becomes_protocol_ready() -> None:
    calls = 0
    service = RequiredMcpService(
        service_id="factory",
        transport=StreamableHttpServerParameters(
            url="http://factory-mcp:8001/mcp", bearer_token="test-token"
        ),
        required_tool_names=frozenset({"list_products"}),
    )

    async def probe(_transport, *, required_tool_names):
        nonlocal calls
        calls += 1
        assert required_tool_names == frozenset({"list_products"})
        if calls in {1, 3}:
            raise OSError("MCP transport is unavailable")
        return object()

    with pytest.raises(AgentApiReadinessError, match="factory"):
        asyncio.run(check_required_mcp_services((service,), probe=probe))

    asyncio.run(check_required_mcp_services((service,), probe=probe))
    assert calls == 2

    with pytest.raises(AgentApiReadinessError, match="factory"):
        asyncio.run(check_required_mcp_services((service,), probe=probe))
    assert calls == 3
