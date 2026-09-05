"""Temporary MCP SDK v2 to LangChain tool compatibility adapter.

Review this module when a stable langchain-mcp-adapters release supports MCP SDK v2.
"""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
import httpx2
from langchain_core.tools import BaseTool, StructuredTool
from mcp import ClientSession
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel, ConfigDict, Field, create_model

from industrial_ai_agent.agent.mcp_tool_provider import (
    McpServerSession,
    McpToolProvider,
    McpToolSession,
)
from industrial_ai_agent.agent.tool_policy import (
    ToolPolicy,
    get_troubleshooting_tool_policy,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpServiceUnavailableError,
)
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    FactoryMcpTransport,
    McpTransport,
    open_mcp_session,
)

DEFAULT_ALLOWED_FACTORY_TOOLS = frozenset(
    {"get_product_history", "get_machine_status", "create_maintenance_ticket"}
)
DEFAULT_ALLOWED_KNOWLEDGE_TOOLS = frozenset({"search_documentation"})


@dataclass(frozen=True, slots=True)
class McpServerConfiguration:
    """One explicitly authorized MCP server for a single agent run."""

    server_id: str
    transport: McpTransport
    allowed_tool_names: frozenset[str]

    def __post_init__(self) -> None:
        if not self.server_id.strip():
            raise ValueError("MCP server_id must not be empty")
        if not self.allowed_tool_names:
            raise ValueError("At least one MCP tool must be authorized per server")


class McpLangChainToolProvider(McpToolProvider):
    """Open configured MCP sessions and translate authorized discovered tools."""

    def __init__(
        self,
        transport_or_servers: FactoryMcpTransport | Sequence[McpServerConfiguration],
        *,
        allowed_tool_names: frozenset[str] = DEFAULT_ALLOWED_FACTORY_TOOLS,
    ) -> None:
        if isinstance(transport_or_servers, (tuple, list)):
            self._servers = tuple(transport_or_servers)
        else:
            self._servers = (
                McpServerConfiguration(
                    server_id="factory",
                    transport=cast(McpTransport, transport_or_servers),
                    allowed_tool_names=allowed_tool_names,
                ),
            )
        if not self._servers:
            raise ValueError("At least one MCP server must be configured")
        server_ids = tuple(server.server_id for server in self._servers)
        if len(set(server_ids)) != len(server_ids):
            raise ValueError("MCP server IDs must be unique")

    def open_session(self) -> AbstractAsyncContextManager[McpToolSession]:
        return self._open_session()

    @asynccontextmanager
    async def _open_session(self) -> AsyncIterator[McpToolSession]:
        """Initialize, discover, authorize, and close one session per server."""
        try:
            async with AsyncExitStack() as stack:
                authorized_tools: list[BaseTool] = []
                authorized_tool_policies: list[ToolPolicy] = []
                discovered_tool_names: list[str] = []
                server_sessions: list[McpServerSession] = []
                seen_tool_names: set[str] = set()
                for configuration in self._servers:
                    client = await stack.enter_async_context(
                        open_mcp_session(configuration.transport)
                    )
                    initialized = await client.initialize()
                    listed_tools = await client.list_tools()
                    server_tool_names = tuple(tool.name for tool in listed_tools.tools)
                    duplicate_names = seen_tool_names.intersection(server_tool_names)
                    if duplicate_names:
                        duplicates = ", ".join(sorted(duplicate_names))
                        raise RuntimeError(
                            f"Duplicate MCP tool names discovered: {duplicates}"
                        )
                    seen_tool_names.update(server_tool_names)
                    discovered_by_name = {
                        tool.name: tool for tool in listed_tools.tools
                    }
                    missing_tools = configuration.allowed_tool_names.difference(
                        discovered_by_name
                    )
                    if missing_tools:
                        missing = ", ".join(sorted(missing_tools))
                        raise RuntimeError(
                            f"Required MCP tools were not discovered from "
                            f"{configuration.server_id}: {missing}"
                        )
                    try:
                        policies = tuple(
                            get_troubleshooting_tool_policy(tool_name)
                            for tool_name in configuration.allowed_tool_names
                        )
                    except ValueError as error:
                        raise RuntimeError(
                            f"MCP server {configuration.server_id} configured an "
                            "unauthorized tool"
                        ) from error
                    authorized_tools.extend(
                        _create_langchain_tool(tool, client)
                        for tool in listed_tools.tools
                        if tool.name in configuration.allowed_tool_names
                    )
                    authorized_tool_policies.extend(policies)
                    discovered_tool_names.extend(server_tool_names)
                    server_sessions.append(
                        McpServerSession(
                            server_id=configuration.server_id,
                            server_name=initialized.server_info.name,
                            server_version=initialized.server_info.version,
                            protocol_version=initialized.protocol_version,
                            discovered_tool_names=server_tool_names,
                        )
                    )
                first_server = server_sessions[0]
                yield McpToolSession(
                    tools=tuple(authorized_tools),
                    discovered_tool_names=tuple(discovered_tool_names),
                    server_name=(
                        first_server.server_name
                        if len(server_sessions) == 1
                        else "multiple"
                    ),
                    server_version=(
                        first_server.server_version
                        if len(server_sessions) == 1
                        else "multiple"
                    ),
                    protocol_version=(
                        first_server.protocol_version
                        if len(server_sessions) == 1
                        else "multiple"
                    ),
                    servers=tuple(server_sessions),
                    tool_policies=tuple(authorized_tool_policies),
                )
        except* (OSError, TimeoutError, httpx.HTTPError, httpx2.HTTPError) as error:
            raise McpServiceUnavailableError("MCP service is unavailable") from error


def _create_langchain_tool(tool: Tool, client: ClientSession) -> BaseTool:
    arguments_schema = _create_arguments_schema(tool)

    async def invoke_mcp_tool(**arguments: object) -> str:
        try:
            response = await client.call_tool(tool.name, dict(arguments))
        except (OSError, TimeoutError, httpx.HTTPError, httpx2.HTTPError) as error:
            raise McpServiceUnavailableError("MCP service is unavailable") from error
        if not isinstance(response, CallToolResult):
            raise McpServiceUnavailableError(
                "MCP tool did not return a completed result"
            )
        if response.is_error or response.structured_content is None:
            raise McpServiceUnavailableError(
                "MCP tool did not return structured content"
            )
        return json.dumps(response.structured_content, sort_keys=True)

    return StructuredTool.from_function(
        coroutine=invoke_mcp_tool,
        name=tool.name,
        description=tool.description,
        args_schema=arguments_schema,
    )


def _create_arguments_schema(tool: Tool) -> type[BaseModel]:
    """Translate strict MCP JSON Schema into the LangChain Pydantic boundary."""
    schema = tool.input_schema
    properties = schema.get("properties")
    required = schema.get("required", ())
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, Mapping)
        or not isinstance(required, list)
    ):
        raise TypeError(f"MCP tool {tool.name} has an unsupported input schema")

    fields: dict[str, tuple[object, object]] = {}
    required_names = set(required)
    for field_name, field_schema in properties.items():
        if not isinstance(field_name, str) or not isinstance(field_schema, Mapping):
            raise TypeError(f"MCP tool {tool.name} has an unsupported input schema")
        python_type = _json_schema_to_pydantic_type(field_schema)
        default = ... if field_name in required_names else None
        fields[field_name] = (python_type, default)

    return create_model(
        f"{_to_pascal_case(tool.name)}Arguments",
        __config__=ConfigDict(extra="forbid", strict=True),
        **fields,
    )


def _json_schema_to_pydantic_type(field_schema: Mapping[str, object]) -> object:
    json_type = field_schema.get("type")
    if json_type == "string":
        return Annotated[
            str,
            Field(
                min_length=_integer_keyword(field_schema, "minLength"),
                max_length=_integer_keyword(field_schema, "maxLength"),
                pattern=_string_keyword(field_schema, "pattern"),
            ),
        ]
    if json_type == "integer":
        return Annotated[
            int,
            Field(
                ge=_number_keyword(field_schema, "minimum"),
                le=_number_keyword(field_schema, "maximum"),
            ),
        ]
    if json_type == "number":
        return Annotated[
            float,
            Field(
                ge=_number_keyword(field_schema, "minimum"),
                le=_number_keyword(field_schema, "maximum"),
            ),
        ]
    if json_type == "boolean":
        return bool
    raise ValueError("MCP tool input schema contains an unsupported JSON type")


def _integer_keyword(schema: Mapping[str, object], key: str) -> int | None:
    value = schema.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number_keyword(schema: Mapping[str, object], key: str) -> float | None:
    value = schema.get(key)
    return (
        float(value)
        if isinstance(value, int | float) and not isinstance(value, bool)
        else None
    )


def _string_keyword(schema: Mapping[str, object], key: str) -> str | None:
    value = schema.get(key)
    return value if isinstance(value, str) else None


def _to_pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))
