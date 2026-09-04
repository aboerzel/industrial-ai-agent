from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from langchain_core.tools import BaseTool, StructuredTool
from mcp.client.stdio import StdioServerParameters
from pydantic import BaseModel, ConfigDict

from industrial_ai_agent.agent.agent_run import (
    AgentRunStatus,
)
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
from industrial_ai_agent.agent.mcp_tool_provider import McpToolProvider, McpToolSession
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressDeniedError,
)
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    McpLangChainToolProvider,
)

PROFILE = ModelProfile("troubleshooting")


class FakeLLMClient:
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        assert profile == PROFILE
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("Unexpected model call")
        return self._responses.pop(0)


@dataclass(frozen=True)
class StaticExecutionZoneResolver:
    zone: ExecutionZone

    def get_execution_zone(self, profile_name: str) -> ExecutionZone:
        del profile_name
        return self.zone


def _tool_response(
    name: str,
    arguments: dict[str, object],
    call_id: str,
) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(LLMToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _final_response() -> LLMResponse:
    return LLMResponse(text="Investigation complete.", finish_reason=FinishReason.STOP)


def _two_tool_responses() -> tuple[LLMResponse, ...]:
    return (
        _tool_response("get_product_history", {"product_id": "P4711"}, "history"),
        _tool_response("get_machine_status", {"station_id": "S04"}, "status"),
        _final_response(),
    )


def _mcp_agent(llm_client: FakeLLMClient) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(llm_client, PROFILE),
        mcp_tool_provider=McpLangChainToolProvider(_factory_server_parameters()),
    )


def _http_mcp_agent(
    llm_client: FakeLLMClient,
    transport: StreamableHttpServerParameters,
) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(llm_client, PROFILE),
        mcp_tool_provider=McpLangChainToolProvider(transport),
    )


def _factory_server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
    )


def test_mcp_discovery_creates_authorized_langchain_tools_with_compatible_schemas() -> (
    None
):
    provider = McpLangChainToolProvider(_factory_server_parameters())

    async def discover() -> McpToolSession:
        async with provider.open_session() as opened_session:
            return opened_session

    discovered_session = asyncio.run(discover())
    tools_by_name = {tool.name: tool for tool in discovered_session.tools}

    assert discovered_session.server_name == "factory_mcp"
    assert discovered_session.protocol_version
    assert discovered_session.discovered_tool_names == (
        "get_product_history",
        "get_machine_status",
    )
    assert set(tools_by_name) == {"get_product_history", "get_machine_status"}
    assert (
        _input_schema(tools_by_name["get_product_history"])["properties"]["product_id"][
            "type"
        ]
        == "string"
    )
    assert (
        _input_schema(tools_by_name["get_machine_status"])["properties"]["station_id"][
            "type"
        ]
        == "string"
    )


def test_langgraph_mcp_http_path_matches_the_stdio_path(
    factory_mcp_http_transport: StreamableHttpServerParameters,
) -> None:
    stdio_llm = FakeLLMClient(*_two_tool_responses())
    http_llm = FakeLLMClient(*_two_tool_responses())

    stdio_result = asyncio.run(
        _mcp_agent(stdio_llm).aanswer_via_mcp("Investigate P4711.")
    )
    http_result = asyncio.run(
        _http_mcp_agent(http_llm, factory_mcp_http_transport).aanswer_via_mcp(
            "Investigate P4711."
        )
    )

    assert http_result.status is stdio_result.status is AgentRunStatus.SUCCESS
    assert http_result.executed_tool_calls == stdio_result.executed_tool_calls
    assert http_result.tool_call_count == stdio_result.tool_call_count == 2
    assert http_result.final_answer == stdio_result.final_answer
    assert _tool_contents(http_llm) == _tool_contents(stdio_llm)
    assert _tool_definitions(http_llm.requests[0]) == _tool_definitions(
        stdio_llm.requests[0]
    )


def test_mcp_run_opens_one_session_for_multiple_sequential_tool_calls() -> None:
    provider = _CountingMcpToolProvider()
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(FakeLLMClient(*_two_tool_responses()), PROFILE),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate P4711."))

    assert result.status is AgentRunStatus.SUCCESS
    assert provider.open_count == 1
    assert provider.closed_count == 1
    assert provider.invocations == [
        ("get_product_history", {"product_id": "P4711"}),
        ("get_machine_status", {"station_id": "S04"}),
    ]


def test_mcp_path_keeps_final_egress_check_before_any_provider_call() -> None:
    underlying_client = FakeLLMClient(_final_response())
    checked_client = EgressCheckedLLMClient(
        underlying_client,
        StaticExecutionZoneResolver(ExecutionZone.PUBLIC_CLOUD),
        DataClassification.CONFIDENTIAL,
    )
    agent = _mcp_agent_with_client(checked_client, _CountingMcpToolProvider())

    with pytest.raises(ModelEgressDeniedError, match="egress denied"):
        asyncio.run(agent.aanswer_via_mcp("Investigate P4711."))

    assert underlying_client.requests == []


def _mcp_agent_with_client(
    llm_client: EgressCheckedLLMClient,
    provider: _CountingMcpToolProvider,
) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(llm_client, PROFILE),
        mcp_tool_provider=cast(McpToolProvider, cast(object, provider)),
    )


def _tool_contents(llm_client: FakeLLMClient) -> tuple[dict[str, object], ...]:
    contents: list[dict[str, object]] = []
    for request in llm_client.requests[1:-1]:
        content = request.messages[-1].content
        assert isinstance(content, str)
        contents.append(json.loads(content))
    return tuple(contents)


def _input_schema(tool: BaseTool) -> dict[str, Any]:
    schema_type = tool.get_input_schema()
    # noinspection PyUnresolvedReferences
    return cast(dict[str, Any], schema_type.model_json_schema())


def _tool_definitions(request: LLMRequest) -> tuple[tuple[str, dict[str, object]], ...]:
    return tuple((tool.name, tool.parameters) for tool in request.tools)


@dataclass
class _CountingMcpToolProvider:
    open_count: int = 0
    closed_count: int = 0
    invocations: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        self.open_count += 1

        async def product_history(product_id: str) -> str:
            self.invocations.append(("get_product_history", {"product_id": product_id}))
            return json.dumps({"product_id": product_id, "found": True, "steps": []})

        async def machine_status(station_id: str) -> str:
            self.invocations.append(("get_machine_status", {"station_id": station_id}))
            return json.dumps(
                {"station_id": station_id, "found": True, "state": "FAULTED"}
            )

        try:
            yield McpToolSession(
                tools=(
                    StructuredTool.from_function(
                        coroutine=product_history,
                        name="get_product_history",
                        description="Get product history.",
                        args_schema=ProductHistoryArguments,
                    ),
                    StructuredTool.from_function(
                        coroutine=machine_status,
                        name="get_machine_status",
                        description="Get machine status.",
                        args_schema=MachineStatusArguments,
                    ),
                ),
                discovered_tool_names=(
                    "get_product_history",
                    "get_machine_status",
                ),
                server_name="fake_factory_mcp",
                server_version="test",
                protocol_version="test",
            )
        finally:
            self.closed_count += 1


class ProductHistoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str


class MachineStatusArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str
