"""Inner orchestration boundary for MCP-discovered LangChain tools."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from langchain_core.tools import BaseTool

from industrial_ai_agent.agent.tool_policy import (
    ToolPolicy,
    get_troubleshooting_tool_policy,
)


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
    tool_policies: tuple[ToolPolicy, ...] = ()

    def __post_init__(self) -> None:
        if not self.tool_policies:
            object.__setattr__(
                self,
                "tool_policies",
                tuple(
                    get_troubleshooting_tool_policy(tool.name) for tool in self.tools
                ),
            )
        policy_names = {policy.name for policy in self.tool_policies}
        tool_names = {tool.name for tool in self.tools}
        if policy_names != tool_names:
            raise ValueError("MCP tool policies must exactly match authorized tools")

    def policy_for(self, tool_name: str) -> ToolPolicy:
        for policy in self.tool_policies:
            if policy.name == tool_name:
                return policy
        raise ValueError(f"No policy is available for tool: {tool_name}")


class McpToolProvider(Protocol):
    """Opens one async MCP tool session for a LangGraph agent run."""

    def open_session(self) -> AbstractAsyncContextManager[McpToolSession]: ...
