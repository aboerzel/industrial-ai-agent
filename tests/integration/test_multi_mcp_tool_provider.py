import asyncio
import inspect
import os
import sys

import pytest
from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_FACTORY_TOOLS,
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)

PROFILE = ModelProfile("local_quality")
_KNOWLEDGE_SERVER_SOURCE = """
import sys
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.infrastructure.knowledge_mcp_server import create_knowledge_mcp_server
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability
class Retriever:
    def search(self, query, limit):
        return (KnowledgeRetrievalResult(content="E-STOP-17 documentation", document_id="error_codes", source="error_codes.md", chunk_id="error_codes::chunk-002", relevance_score=0.9, metadata={"title": "E-STOP-17"}),)[:limit]
create_knowledge_mcp_server(documentation_search=DocumentationSearchCapability(Retriever())).run(transport="stdio")
"""
_FACTORY_SERVER_WITH_UNAUTHORIZED_TOOL_SOURCE = """
from industrial_ai_agent.infrastructure.factory_mcp_server import create_default_factory_mcp_server
from industrial_ai_agent.infrastructure.mcp_schema_validation import require_strict_mcp_tool_arguments

server = create_default_factory_mcp_server()

@server.tool(name="diagnostic_export", structured_output=True)
def diagnostic_export(station_id: str) -> dict[str, str]:
    return {"station_id": station_id}

require_strict_mcp_tool_arguments(server, "diagnostic_export")
server.run(transport="stdio")
"""


class FakeLLMClient:
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        assert profile == PROFILE
        self.requests.append(request)
        return self._responses.pop(0)


def _response(name: str, arguments: dict[str, object], call_id: str) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(LLMToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _provider() -> McpLangChainToolProvider:
    factory_database_url = os.getenv("FACTORY_DATABASE_URL")
    return McpLangChainToolProvider(
        (
            McpServerConfiguration(
                server_id="factory",
                transport=StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "industrial_ai_agent.infrastructure.factory_mcp_server",
                    ],
                    env=(
                        {"FACTORY_DATABASE_URL": factory_database_url}
                        if factory_database_url
                        else None
                    ),
                ),
                allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
            ),
            McpServerConfiguration(
                server_id="knowledge",
                transport=StdioServerParameters(
                    command=sys.executable,
                    args=["-c", _KNOWLEDGE_SERVER_SOURCE],
                ),
                allowed_tool_names=DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
            ),
        )
    )


def test_multi_mcp_discovery_binds_all_unique_authorized_tools_once_per_run() -> None:
    provider = _provider()

    async def discover():
        async with provider.open_session() as opened_session:
            return opened_session

    session = asyncio.run(discover())

    assert [server.server_id for server in session.servers] == ["factory", "knowledge"]
    assert session.discovered_tool_names == (
        "list_stations",
        "get_station_overview",
        "list_products",
        "get_product_overview",
        "get_product_history",
        "get_machine_status",
        "get_maintenance_ticket",
        "create_maintenance_ticket",
        "search_documentation",
    )
    assert [tool.name for tool in session.tools] == list(session.discovered_tool_names)


def test_discovered_tool_outside_allowlist_is_not_bound_to_the_agent() -> None:
    provider = McpLangChainToolProvider(
        (
            McpServerConfiguration(
                server_id="factory",
                transport=StdioServerParameters(
                    command=sys.executable,
                    args=["-c", _FACTORY_SERVER_WITH_UNAUTHORIZED_TOOL_SOURCE],
                ),
                allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
            ),
        )
    )

    async def discover():
        async with provider.open_session() as opened_session:
            return opened_session

    session = asyncio.run(discover())

    assert "diagnostic_export" in session.discovered_tool_names
    assert "diagnostic_export" not in {tool.name for tool in session.tools}


def test_multi_mcp_langgraph_run_is_sequential_and_has_no_direct_retriever_access() -> (
    None
):
    llm = FakeLLMClient(
        _response("get_product_history", {"product_id": "P4711"}, "history"),
        _response("get_machine_status", {"station_id": "S04"}, "status"),
        _response(
            "search_documentation",
            {"query": "E-STOP-17 at S04", "top_k": 3},
            "documentation",
        ),
        LLMResponse(text="Diagnosis complete.", finish_reason=FinishReason.STOP),
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(llm, PROFILE),
        mcp_tool_provider=_provider(),
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate P4711."))

    assert [call.tool for call in result.executed_tool_calls] == [
        "get_product_history",
        "get_machine_status",
        "search_documentation",
    ]
    assert all(len(request.tools) == 8 for request in llm.requests)
    agent_source = inspect.getsource(LangGraphTroubleshootingAgent)
    assert "ProductHistoryCapability" not in agent_source
    assert "MachineStatusCapability" not in agent_source
    assert "KnowledgeRetriever" not in agent_source
    assert "DocumentationSearchCapability" not in agent_source


def test_duplicate_discovered_tool_names_fail_closed() -> None:
    factory_database_url = os.getenv("FACTORY_DATABASE_URL")
    duplicate_factory_transport = StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
        env=(
            {"FACTORY_DATABASE_URL": factory_database_url}
            if factory_database_url
            else None
        ),
    )
    provider = McpLangChainToolProvider(
        (
            McpServerConfiguration(
                server_id="first",
                transport=duplicate_factory_transport,
                allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
            ),
            McpServerConfiguration(
                server_id="second",
                transport=duplicate_factory_transport,
                allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
            ),
        )
    )

    async def discover() -> None:
        async with provider.open_session():
            pass

    with pytest.raises(BaseExceptionGroup) as raised:
        asyncio.run(discover())

    assert any(
        isinstance(error, RuntimeError)
        and "Duplicate MCP tool names discovered" in str(error)
        for error in _flatten_exception_group(raised.value)
    )


def _flatten_exception_group(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [
            nested
            for item in error.exceptions
            for nested in _flatten_exception_group(item)
        ]
    return [error]
