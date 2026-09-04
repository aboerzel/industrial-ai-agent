"""MCP server adapter for the read-only factory capabilities."""

from typing import Any

from mcp.server.mcpserver import MCPServer

from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

FACTORY_MCP_SERVER_NAME = "factory_mcp"
FACTORY_MCP_SERVER_VERSION = "0.1.0"


def create_factory_mcp_server(
    *,
    product_history: ProductHistoryCapability,
    machine_status: MachineStatusCapability,
) -> MCPServer:
    """Create an MCP adapter over the injected factory capabilities."""
    server = MCPServer(
        name=FACTORY_MCP_SERVER_NAME,
        version=FACTORY_MCP_SERVER_VERSION,
        description="Read-only factory information tools.",
    )

    @server.tool(
        name="get_product_history",
        description="Get historical production information for a product ID.",
        structured_output=True,
    )
    def get_product_history(product_id: str) -> dict[str, Any]:
        result = product_history.get_product_history(product_id)
        return result.model_dump(mode="json")

    @server.tool(
        name="get_machine_status",
        description="Get the current operating state of a station ID.",
        structured_output=True,
    )
    def get_machine_status(station_id: str) -> dict[str, Any]:
        result = machine_status.get_machine_status(station_id)
        return result.model_dump(mode="json")

    return server


def create_default_factory_mcp_server() -> MCPServer:
    """Build the local demo server at the Infrastructure composition root."""
    return create_factory_mcp_server(
        product_history=ProductHistoryCapability(InMemoryProductHistoryRepository()),
        machine_status=MachineStatusCapability(InMemoryMachineStatusRepository()),
    )


def main() -> None:
    create_default_factory_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
