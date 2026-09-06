from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
)
from industrial_ai_agent.infrastructure.troubleshooting_run_composition import (
    _mcp_server_configurations,
)


def test_public_run_connects_only_to_its_authorized_read_only_servers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN", "test-public-token")
    policy = AgentRunClassificationPolicy().resolve(AgentRunProfile.PUBLIC_INFORMATION)

    servers = _mcp_server_configurations(
        mcp_transport="http",
        factory_mcp_url="http://factory.example/mcp",
        knowledge_mcp_url="http://knowledge.example/mcp",
        factory_database_url=None,
        run_policy=policy,
    )

    assert [server.server_id for server in servers] == ["factory", "knowledge"]
    assert servers[0].allowed_tool_names == frozenset(
        {
            "list_stations",
            "get_station_overview",
            "list_products",
            "get_product_overview",
        }
    )
    assert servers[1].allowed_tool_names == frozenset({"search_documentation"})
