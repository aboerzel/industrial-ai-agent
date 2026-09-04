"""Inner orchestration boundary for MCP-discovered LangChain tools."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import BaseTool


@dataclass(frozen=True, slots=True)
class McpServerSession:
    """Protocol metadata discovered from one explicitly configured MCP server."""

    server_id: str
    server_name: str
    server_version: str
    protocol_version: str
    discovered_tool_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class McpToolSession:
    """Authorized tools and protocol metadata for one agent-run MCP session."""

    tools: tuple[BaseTool, ...]
    discovered_tool_names: tuple[str, ...]
    server_name: str
    server_version: str
    protocol_version: str
    servers: tuple[McpServerSession, ...] = ()


class McpToolProvider(Protocol):
    """Opens one async MCP tool session for a LangGraph agent run."""

    def open_session(self) -> AbstractAsyncContextManager[McpToolSession]: ...
