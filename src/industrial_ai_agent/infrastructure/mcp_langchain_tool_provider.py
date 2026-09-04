"""Temporary MCP SDK v2 to LangChain tool compatibility adapter.

Review this module when a stable langchain-mcp-adapters release supports MCP SDK v2.
"""

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from langchain_core.tools import BaseTool, StructuredTool
from mcp import ClientSession
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel, ConfigDict, create_model

from industrial_ai_agent.agent.mcp_tool_provider import McpToolProvider, McpToolSession
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    FactoryMcpTransport,
    open_factory_mcp_session,
)

DEFAULT_ALLOWED_FACTORY_TOOLS = frozenset({"get_product_history", "get_machine_status"})


class McpToolInvocationError(RuntimeError):
    """Raised when a discovered MCP tool cannot provide structured content."""


class McpLangChainToolProvider(McpToolProvider):
    """Open one MCP session and translate authorized discovered tools."""

    def __init__(
        self,
        transport: FactoryMcpTransport,
        *,
        allowed_tool_names: frozenset[str] = DEFAULT_ALLOWED_FACTORY_TOOLS,
    ) -> None:
        if not allowed_tool_names:
            raise ValueError("At least one MCP tool must be authorized")
        self._transport = transport
        self._allowed_tool_names = allowed_tool_names

    def open_session(self) -> AbstractAsyncContextManager[McpToolSession]:
        return self._open_session()

    @asynccontextmanager
    async def _open_session(self) -> AsyncIterator[McpToolSession]:
        """Initialize, discover, authorize, and close one MCP session."""
        async with open_factory_mcp_session(self._transport) as client:
            initialized = await client.initialize()
            listed_tools = await client.list_tools()
            discovered_by_name = {tool.name: tool for tool in listed_tools.tools}
            missing_tools = self._allowed_tool_names.difference(discovered_by_name)
            if missing_tools:
                missing = ", ".join(sorted(missing_tools))
                raise RuntimeError(f"Required MCP tools were not discovered: {missing}")
            authorized_tools = tuple(
                _create_langchain_tool(tool, client)
                for tool in listed_tools.tools
                if tool.name in self._allowed_tool_names
            )
            yield McpToolSession(
                tools=authorized_tools,
                discovered_tool_names=tuple(tool.name for tool in listed_tools.tools),
                server_name=initialized.server_info.name,
                server_version=initialized.server_info.version,
                protocol_version=initialized.protocol_version,
            )


def _create_langchain_tool(tool: Tool, client: ClientSession) -> BaseTool:
    arguments_schema = _create_arguments_schema(tool)

    async def invoke_mcp_tool(**arguments: object) -> str:
        response = await client.call_tool(tool.name, dict(arguments))
        if not isinstance(response, CallToolResult):
            raise McpToolInvocationError(
                f"MCP tool {tool.name} did not return a completed result"
            )
        if response.is_error or response.structured_content is None:
            raise McpToolInvocationError(
                f"MCP tool {tool.name} did not return structured content"
            )
        return json.dumps(response.structured_content, sort_keys=True)

    return StructuredTool.from_function(
        coroutine=invoke_mcp_tool,
        name=tool.name,
        description=tool.description,
        args_schema=arguments_schema,
    )


def _create_arguments_schema(tool: Tool) -> type[BaseModel]:
    """Translate the small supported MCP JSON-schema subset to a Pydantic model."""
    schema = tool.input_schema
    properties = schema.get("properties")
    required = schema.get("required", ())
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise TypeError(f"MCP tool {tool.name} has an unsupported input schema")

    fields: dict[str, tuple[type[object], object]] = {}
    required_names = set(required)
    for field_name, field_schema in properties.items():
        if not isinstance(field_name, str) or not isinstance(field_schema, Mapping):
            raise TypeError(f"MCP tool {tool.name} has an unsupported input schema")
        json_type = field_schema.get("type")
        python_type = _json_type_to_python_type(json_type)
        default = ... if field_name in required_names else None
        fields[field_name] = (python_type, default)

    return create_model(
        f"{_to_pascal_case(tool.name)}Arguments",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _json_type_to_python_type(json_type: object) -> type[object]:
    if json_type == "string":
        return str
    if json_type == "integer":
        return int
    if json_type == "number":
        return float
    if json_type == "boolean":
        return bool
    raise ValueError("MCP tool input schema contains an unsupported JSON type")


def _to_pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))
