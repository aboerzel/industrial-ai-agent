"""Official-SDK client path for factory MCP transports."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import Tool

from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    instrument_mcp_http_client,
)


@dataclass(frozen=True)
class StreamableHttpServerParameters:
    """Network endpoint for one stateful Streamable HTTP MCP session."""

    url: str
    bearer_token: str | None = field(default=None, repr=False)
    request_headers: Mapping[str, str] = field(
        default_factory=dict,
        repr=False,
    )


type McpTransport = StdioServerParameters | StreamableHttpServerParameters
# Compatibility alias for existing factory-only callers.
type FactoryMcpTransport = McpTransport


@dataclass(frozen=True)
class FactoryMcpSmokeResult:
    """Protocol discovery and structured results returned by a factory MCP server."""

    server_name: str
    server_version: str
    protocol_version: str
    tool_names: tuple[str, ...]
    tool_schemas: dict[str, dict[str, Any]]
    product_history: dict[str, Any] | None
    machine_status: dict[str, Any] | None
    unknown_product_history: dict[str, Any] | None
    unknown_machine_status: dict[str, Any] | None


@asynccontextmanager
async def open_mcp_session(
    transport: McpTransport,
    *,
    telemetry: Telemetry | None = None,
) -> AsyncIterator[ClientSession]:
    """Open and close one official-SDK session for either supported transport."""
    async with AsyncExitStack() as stack:
        if isinstance(transport, StdioServerParameters):
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(transport)
            )
        else:
            headers = dict(transport.request_headers)
            if transport.bearer_token:
                headers["Authorization"] = f"Bearer {transport.bearer_token}"
            http_client = await stack.enter_async_context(
                create_mcp_http_client(headers or None)
            )
            # The public HTTP-client request hook injects W3C context for each
            # real Streamable HTTP request, not once per MCP session.
            instrument_mcp_http_client(http_client, telemetry)
            read_stream, write_stream = await stack.enter_async_context(
                streamable_http_client(transport.url, http_client=http_client)
            )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        yield session


async def run_factory_mcp_smoke(
    transport: FactoryMcpTransport,
) -> FactoryMcpSmokeResult:
    """Discover and call the read-only tools through an initialized MCP session."""
    async with open_mcp_session(transport) as session:
        initialized = await session.initialize()
        listed_tools = await session.list_tools()
        product_history = await session.call_tool(
            "get_product_history", {"product_id": "P4711"}
        )
        machine_status = await session.call_tool(
            "get_machine_status", {"station_id": "S04"}
        )
        unknown_product_history = await session.call_tool(
            "get_product_history", {"product_id": "P9999"}
        )
        unknown_machine_status = await session.call_tool(
            "get_machine_status", {"station_id": "S99"}
        )

    return FactoryMcpSmokeResult(
        server_name=initialized.server_info.name,
        server_version=initialized.server_info.version,
        protocol_version=initialized.protocol_version,
        tool_names=tuple(tool.name for tool in listed_tools.tools),
        tool_schemas=_tool_schemas(listed_tools.tools),
        product_history=product_history.structured_content,
        machine_status=machine_status.structured_content,
        unknown_product_history=unknown_product_history.structured_content,
        unknown_machine_status=unknown_machine_status.structured_content,
    )


def _tool_schemas(tools: Sequence[Tool]) -> dict[str, dict[str, Any]]:
    return {tool.name: dict(tool.input_schema) for tool in tools}
