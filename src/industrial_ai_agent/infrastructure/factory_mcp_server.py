"""MCP server adapter and deployment entry point for factory capabilities."""

import argparse
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from industrial_ai_agent.domain.security import DEMO_ENGINEER_SECURITY_CONTEXT
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlMachineStatusRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

FACTORY_MCP_SERVER_NAME = "factory_mcp"
FACTORY_MCP_SERVER_VERSION = "0.1.0"
FACTORY_MCP_HTTP_PATH = "/mcp"


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
    """Build the persistent service when configured, retaining in-memory stdio tests."""
    database_url = os.getenv("FACTORY_DATABASE_URL")
    if database_url:
        session_factory = PostgreSqlSessionFactory(database_url)
        return create_factory_mcp_server(
            product_history=ProductHistoryCapability(
                PostgreSqlProductHistoryRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
            machine_status=MachineStatusCapability(
                PostgreSqlMachineStatusRepository(
                    session_factory, DEMO_ENGINEER_SECURITY_CONTEXT
                )
            ),
        )
    return create_factory_mcp_server(
        product_history=ProductHistoryCapability(InMemoryProductHistoryRepository()),
        machine_status=MachineStatusCapability(InMemoryMachineStatusRepository()),
    )


def main() -> None:
    """Run the demo server through the transport chosen at process startup."""
    args = _parse_args()
    server = create_default_factory_mcp_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=FACTORY_MCP_HTTP_PATH,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the factory MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("FACTORY_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("FACTORY_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FACTORY_MCP_PORT", "8001")),
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
