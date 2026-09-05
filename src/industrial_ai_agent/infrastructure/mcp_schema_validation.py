"""Configure the MCP SDK's generated argument models for strict tool input."""

from mcp.server.mcpserver import MCPServer
from pydantic import ConfigDict


def require_strict_mcp_tool_arguments(server: MCPServer, tool_name: str) -> None:
    """Make the SDK-generated Pydantic model reject coercion and extra fields.

    MCP SDK 2.1 generates a Pydantic argument model from the Python signature, but
    its public decorator currently offers no argument-model configuration hook. The
    model remains the SDK validation mechanism; this infrastructure-bound adjustment
    only changes its Pydantic configuration and published JSON Schema.
    """
    # noinspection PyProtectedMember
    tool = server._tool_manager.get_tool(tool_name)
    if tool is None:
        raise RuntimeError(f"MCP tool was not registered: {tool_name}")
    argument_model = tool.fn_metadata.arg_model
    argument_model.model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        strict=True,
    )
    argument_model.model_rebuild(force=True)
    tool.parameters = argument_model.model_json_schema(by_alias=True)
